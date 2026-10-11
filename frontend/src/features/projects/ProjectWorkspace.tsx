import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiClient, SafeAppClientError } from '../../api/client';
import {
  BriefRevisionResponse,
  ExportResponse,
  GenerationAdmissionResponse,
  GenerationSnapshotResponse,
  PresentationClipItem,
  ProjectSummary,
  ReviewResponse,
} from '../../api/types';
import { useAppContext } from '../../app/providers';
import { BriefEditor } from '../brief/BriefEditor';
import { JobTimeline } from '../generation/JobTimeline';
import { ClipOrderer } from '../presentation/ClipOrderer';
import { ExportPanel } from '../presentation/ExportPanel';
import { QuoteCard } from '../quotes/QuoteCard';
import { ImageCompare } from '../review/ImageCompare';
import { ReviewChecklist } from '../review/ReviewChecklist';
import { VideoReview } from '../review/VideoReview';
import { RoomList } from '../rooms/RoomList';
import { RoomViewer } from '../rooms/RoomViewer';

export function ProjectWorkspace() {
  const { projectId, roomId } = useParams<{ projectId: string; roomId?: string }>();
  const navigate = useNavigate();
  const { setConnectionState } = useAppContext();

  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [activeBrief, setActiveBrief] = useState<BriefRevisionResponse | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobSnapshot, setJobSnapshot] = useState<GenerationSnapshotResponse | null>(null);
  const [selectedKind, setSelectedKind] = useState<'image' | 'video'>('image');
  const [autoQuoteNonce, setAutoQuoteNonce] = useState<number>(0);
  const [isRevisionQuoteActive, setIsRevisionQuoteActive] = useState<boolean>(false);
  const [hasEnteredQuoteFlow, setHasEnteredQuoteFlow] = useState<boolean>(false);
  const [revisionBanner, setRevisionBanner] = useState<string | null>(null);
  const [quickPhotoReviseNotes, setQuickPhotoReviseNotes] = useState('');
  const [revisingPhoto, setRevisingPhoto] = useState(false);
  const [draftBrief, setDraftBrief] = useState<{
    raw_text: string;
    preserve: string[];
    layout_mode: 'preserve' | 'conceptual_change';
    isDirty: boolean;
  } | null>(null);
  const [exportData, setExportData] = useState<ExportResponse | null>(null);
  const [isAssembling, setIsAssembling] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const flowTopRef = React.useRef<HTMLDivElement>(null);

  const scrollToFlowTop = useCallback(() => {
    requestAnimationFrame(() => {
      if (flowTopRef.current && typeof flowTopRef.current.scrollIntoView === 'function') {
        flowTopRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else if (typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    });
  }, []);

  const reloadProjectAndRoomState = useCallback(
    async (projId: string, targetRoomId?: string) => {
      const proj = await apiClient.getProject(projId);
      setProject(proj);
      const rm = proj.rooms.find((r) => r.id === targetRoomId) || proj.rooms[0];
      if (rm) {
        const brief = await apiClient.getLatestRoomBrief(rm.id);
        setActiveBrief(brief);

        const existingJobId =
          (typeof window !== 'undefined' ? localStorage.getItem(`mr_active_job_${rm.id}`) : null) ||
          rm.latest_job_id;

        if (existingJobId) {
          setActiveJobId((prev) => prev || existingJobId);
          try {
            const storedProvId =
              typeof window !== 'undefined' ? localStorage.getItem(`mr_provider_id_${existingJobId}`) || undefined : undefined;
            const snap = await apiClient.getGeneration(existingJobId, {
              provider_id: storedProvId,
              room_id: rm.id,
            });
            setJobSnapshot((prev) => {
              if (prev?.state === 'ready_for_review' && snap.state !== 'ready_for_review') return prev;
              return snap;
            });
            if (snap.output_asset_url && typeof window !== 'undefined') {
              localStorage.setItem(`mr_output_url_${rm.id}`, snap.output_asset_url);
            }
            if (snap.state === 'rejected') {
              setIsRevisionQuoteActive(true);
              setHasEnteredQuoteFlow(true);
            }
          } catch {
            // Keep existing state on transient transport glitch
          }
        }
      }
      return proj;
    },
    []
  );

  useEffect(() => {
    if (!projectId) return;
    let mounted = true;
    setHasEnteredQuoteFlow(false);
    setIsRevisionQuoteActive(false);
    setRevisionBanner(null);
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const proj = await reloadProjectAndRoomState(projectId, roomId);
        if (!mounted) return;
        if (!roomId && proj.rooms.length > 0) {
          navigate(`/app/projects/${proj.id}/rooms/${proj.rooms[0].id}`, { replace: true });
        }
      } catch (err) {
        if (mounted) {
          if (err instanceof SafeAppClientError && (err.status === 404 || err.code === 'not_found')) {
            navigate('/app', { replace: true });
            return;
          }
          setError(err instanceof SafeAppClientError ? err.message : 'Project not found.');
        }
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [projectId, roomId, navigate, reloadProjectAndRoomState]);

  const activeRoom = project?.rooms.find((r) => r.id === roomId) || project?.rooms[0];

  const handleAddRoom = async (name: string, roomType: string) => {
    if (!project) return;
    const rm = await apiClient.createRoom(project.id, name, roomType, project.rooms.length);
    await reloadProjectAndRoomState(project.id, rm.id);
    navigate(`/app/projects/${project.id}/rooms/${rm.id}`);
  };

  const handleUploadPhoto = async (file: File) => {
    if (!project || !activeRoom) return;
    const uploadedAsset = await apiClient.uploadRoomPhoto(activeRoom.id, file);
    if (uploadedAsset?.file_path) {
      localStorage.setItem(`mr_file_path_${activeRoom.id}`, uploadedAsset.file_path);
    }
    await reloadProjectAndRoomState(project.id, activeRoom.id);
  };

  const handleSaveBrief = async (payload: {
    raw_text: string;
    preserve: string[];
    layout_mode: 'preserve' | 'conceptual_change';
    resolve_conflicts?: string[];
    accepted_reference_asset_id?: string | null;
  }): Promise<BriefRevisionResponse | void> => {
    if (!project || !activeRoom) return;
    const isRevision = Boolean(activeBrief && jobSnapshot);
    const rev = await apiClient.saveRoomBrief(activeRoom.id, payload);
    if (rev?.compiled_prompt) {
      localStorage.setItem(`mr_brief_prompt_${activeRoom.id}`, rev.compiled_prompt);
    }
    setActiveBrief(rev);
    await reloadProjectAndRoomState(project.id, activeRoom.id);
    if (isRevision && !rev.has_unresolved_conflicts) {
      setIsRevisionQuoteActive(true);
      setHasEnteredQuoteFlow(true);
      setAutoQuoteNonce((n) => n + 1);
      setRevisionBanner(
        `Revision #${rev.revision_number} ready! Pick Photo or Video and confirm your credit quote below to run it.`
      );
      scrollToFlowTop();
    }
    return rev;
  };

  const handleEnsureBriefSaved = useCallback(async (): Promise<BriefRevisionResponse | null> => {
    if (!project || !activeRoom) return activeBrief;
    if (draftBrief && draftBrief.isDirty && draftBrief.raw_text.trim()) {
      const rev = await apiClient.saveRoomBrief(activeRoom.id, {
        raw_text: draftBrief.raw_text.trim(),
        preserve: draftBrief.preserve,
        layout_mode: draftBrief.layout_mode,
        resolve_conflicts: [
          'doors',
          'windows',
          'island',
          'island position',
          'appliance',
          'appliance positions',
          'ceiling',
          'ceiling height',
          'room footprint',
          'camera viewpoint',
          'walls',
          'flooring',
          'cabinets',
          'countertops',
          'lighting',
          'hardware',
          'room finish',
        ],
      });
      if (rev?.compiled_prompt) {
        localStorage.setItem(`mr_brief_prompt_${activeRoom.id}`, rev.compiled_prompt);
      }
      setActiveBrief(rev);
      await reloadProjectAndRoomState(project.id, activeRoom.id);
      return rev;
    }
    return activeBrief;
  }, [project, activeRoom, activeBrief, draftBrief, reloadProjectAndRoomState]);

  const handleQuickRevise = async (
    notes: string,
    kind: 'image' | 'video',
    referenceAssetId?: string
  ) => {
    if (!project || !activeRoom || !notes.trim()) return;
    const rev = await apiClient.saveRoomBrief(activeRoom.id, {
      raw_text: notes.trim().slice(0, 2000),
      preserve: activeBrief?.brief?.preserve || [
        'Room footprint',
        'Camera viewpoint',
        'Doors',
        'Windows',
        'Ceiling height',
      ],
      layout_mode: activeBrief?.brief?.layout_mode || 'preserve',
      resolve_conflicts: [
        'doors',
        'windows',
        'island',
        'island position',
        'appliance',
        'appliance positions',
        'ceiling',
        'ceiling height',
        'room footprint',
        'camera viewpoint',
        'walls',
        'flooring',
        'cabinets',
        'countertops',
        'lighting',
        'hardware',
        'room finish',
      ],
      parent_revision_id: activeBrief?.id || null,
      accepted_reference_asset_id:
        referenceAssetId ||
        (kind === 'image'
          ? stillAssetId || activeRoom.accepted_image_asset_id || null
          : activeRoom.accepted_image_asset_id || null),
    });
    setActiveBrief(rev);
    setSelectedKind(kind);
    setIsRevisionQuoteActive(true);
    setHasEnteredQuoteFlow(true);
    await reloadProjectAndRoomState(project.id, activeRoom.id);
    setAutoQuoteNonce((n) => n + 1);
    setRevisionBanner(
      `Revision #${rev.revision_number} ready! Pick Photo or Video and confirm your credit quote below to run it on Magic Hour.`
    );
    scrollToFlowTop();
  };

  const handleJobStarted = (admission: GenerationAdmissionResponse) => {
    setIsRevisionQuoteActive(false);
    setHasEnteredQuoteFlow(true);
    setAutoQuoteNonce(0);
    setRevisionBanner(null);
    setActiveJobId(admission.job_id);
    if (activeRoom && typeof window !== 'undefined') {
      localStorage.setItem(`mr_active_job_${activeRoom.id}`, admission.job_id);
      if (admission.provider_id) {
        localStorage.setItem(`mr_provider_id_${admission.job_id}`, admission.provider_id);
      }
    }
    const initialKind = (admission.kind || selectedKind) as 'image' | 'video';
    setJobSnapshot({
      job_id: admission.job_id,
      id: admission.job_id,
      provider_id: admission.provider_id,
      project_id: project?.id || 'default',
      room_id: activeRoom?.id || 'default',
      kind: initialKind,
      state: 'queued',
      provider_state: 'queued',
      permitted_next_action: 'wait',
      model: initialKind === 'image' ? 'qwen-edit' : 'kling-v1',
      resolution: initialKind === 'image' ? '640px' : '480p',
      output_asset_url: null,
      events: [
        {
          sequence: 1,
          job_id: admission.job_id,
          state: 'queued',
          safe_message: 'Job submitted to Magic Hour.',
          timestamp: new Date().toISOString(),
          payload: {},
        },
      ],
    } as any);
    scrollToFlowTop();
  };

  const handleJobUpdated = useCallback(
    async (snap: GenerationSnapshotResponse) => {
      const prevState = jobSnapshot?.state;
      setJobSnapshot(snap);
      if (activeRoom && snap.output_asset_url && typeof window !== 'undefined') {
        localStorage.setItem(`mr_output_url_${activeRoom.id}`, snap.output_asset_url);
      }
      if (snap.state === 'ready_for_review' || snap.state === 'accepted') {
        if (projectId) {
          try {
            await reloadProjectAndRoomState(projectId, roomId);
          } catch {
            // Ignore
          }
        }
        try {
          const conn = await apiClient.getConnectionStatus();
          setConnectionState(conn);
        } catch {
          // Ignore
        }
        if (prevState !== snap.state) {
          scrollToFlowTop();
        }
      }
    },
    [jobSnapshot?.state, activeRoom, projectId, roomId, reloadProjectAndRoomState, scrollToFlowTop, setConnectionState]
  );

  const handleReviewed = async (review: ReviewResponse) => {
    if (!project || !activeRoom) return;
    await reloadProjectAndRoomState(project.id, activeRoom.id);
    try {
      const conn = await apiClient.getConnectionStatus();
      setConnectionState(conn);
    } catch {
      // Ignore
    }
    if (review.decision === 'revise') {
      if (jobSnapshot?.kind) {
        setSelectedKind(jobSnapshot.kind);
      }
      setIsRevisionQuoteActive(true);
      setHasEnteredQuoteFlow(true);
      setAutoQuoteNonce((n) => n + 1);
      setRevisionBanner(
        'Revision ready! Pick Photo or Video and click Confirm & Spend below to run your revision on Magic Hour.'
      );
      scrollToFlowTop();
    } else if (review.decision === 'accept') {
      setIsRevisionQuoteActive(false);
      setAutoQuoteNonce(0);
      setRevisionBanner(null);
      scrollToFlowTop();
    } else {
      setIsRevisionQuoteActive(false);
      setAutoQuoteNonce(0);
      scrollToFlowTop();
    }
  };

  const handleAssemblePresentation = async (
    title: string,
    orderedClips: PresentationClipItem[],
    includeConceptLabel: boolean
  ) => {
    if (!project) return;
    setIsAssembling(true);
    setError(null);
    try {
      const job = await apiClient.createPresentation(project.id, title, orderedClips, includeConceptLabel);
      let exp = await apiClient.getExport(job.export_id);
      setExportData(exp);
      for (let i = 0; i < 20 && (exp.status === 'queued' || exp.status === 'rendering'); i++) {
        await new Promise((r) => setTimeout(r, 350));
        exp = await apiClient.getExport(job.export_id);
        setExportData(exp);
      }
    } catch (err) {
      setError(err instanceof SafeAppClientError ? err.message : 'Failed to assemble presentation.');
    } finally {
      setIsAssembling(false);
    }
  };

  const handleRefreshExport = async () => {
    if (!exportData) return;
    const exp = await apiClient.getExport(exportData.export_id);
    setExportData(exp);
  };

  if (loading) {
    return (
      <main style={{ padding: '24px' }} aria-live="polite">
        Loading workspace…
      </main>
    );
  }

  if (error || !project) {
    return (
      <main style={{ padding: '24px' }}>
        <div className="alert alert-error" role="alert">
          {error || 'Project not found.'}
        </div>
      </main>
    );
  }

  const storedOutputUrl =
    typeof window !== 'undefined' && activeRoom ? localStorage.getItem(`mr_output_url_${activeRoom.id}`) : null;

  const rawStillCompareUrl =
    (jobSnapshot?.kind === 'image' && jobSnapshot.output_asset_url) ||
    activeRoom?.accepted_image_url ||
    storedOutputUrl ||
    null;

  const stillAssetId =
    (jobSnapshot?.kind === 'image' && jobSnapshot.output_asset_id) ||
    activeRoom?.accepted_image_asset_id ||
    null;

  const stillCompareUrl = rawStillCompareUrl
    ? `${rawStillCompareUrl}${rawStillCompareUrl.includes('?') ? '&' : '?'}v=${stillAssetId || jobSnapshot?.job_id || 'latest'}`
    : null;

  const stillReviewAssetId =
    jobSnapshot?.kind === 'image' &&
    jobSnapshot.state === 'ready_for_review' &&
    jobSnapshot.output_asset_id
      ? jobSnapshot.output_asset_id
      : null;

  const videoClipUrl =
    (jobSnapshot?.kind === 'video' && jobSnapshot.output_asset_url) ||
    activeRoom?.accepted_clip_url ||
    null;

  const videoClipAssetId =
    (jobSnapshot?.kind === 'video' && jobSnapshot.output_asset_id) ||
    activeRoom?.accepted_clip_asset_id ||
    null;

  const canReviewVideo = Boolean(
    jobSnapshot?.kind === 'video' &&
      jobSnapshot.state === 'ready_for_review' &&
      jobSnapshot.output_asset_id
  );

  const hasAnyAcceptedClip = project.rooms.some((r) => Boolean(r.accepted_clip_asset_id));
  const hasApprovedMediaForRoom = Boolean(
    activeRoom?.accepted_image_url || activeRoom?.accepted_clip_url
  );
  const isCurrentOutputApproved = Boolean(
    hasApprovedMediaForRoom &&
      !isRevisionQuoteActive &&
      jobSnapshot?.state === 'accepted'
  );

  const isJobRunning = Boolean(
    activeJobId &&
      (!jobSnapshot ||
        [
          'admitted',
          'preparing',
          'submitting',
          'submission_unknown',
          'queued',
          'rendering',
          'saving_output',
          'polling_provider',
        ].includes(jobSnapshot.state))
  );

  const isSwitchingToUngeneratedVideo = Boolean(
    selectedKind === 'video' &&
      jobSnapshot &&
      jobSnapshot.kind !== 'video' &&
      !activeRoom?.accepted_clip_asset_id
  );

  const isSwitchingToUngeneratedImage = Boolean(
    selectedKind === 'image' &&
      jobSnapshot &&
      jobSnapshot.kind !== 'image' &&
      !stillCompareUrl
  );

  const showReviewAndOutput = Boolean(
    !isJobRunning &&
      (jobSnapshot?.state === 'ready_for_review' ||
        jobSnapshot?.state === 'accepted' ||
        Boolean(stillCompareUrl) ||
        Boolean(videoClipUrl))
  );

  const shouldShowQuoteCard = Boolean(
    !isJobRunning &&
      !showReviewAndOutput &&
      (!jobSnapshot ||
        isRevisionQuoteActive ||
        ['failed', 'stopped', 'blocked_credits', 'waiting_for_key'].includes(jobSnapshot.state) ||
        isSwitchingToUngeneratedVideo ||
        isSwitchingToUngeneratedImage)
  );

  // Only show Step 1 (Upload Photo) and Step 2 (Brief Editor) before the user enters the quote/generation/review flow
  const showInitialSetup = Boolean(
    !activeJobId && !jobSnapshot && !isRevisionQuoteActive && !hasEnteredQuoteFlow
  );

  const mediaSelectorCard = (
    <div
      className="card"
      style={{ marginBottom: '16px', padding: '16px 20px' }}
      data-testid="media-kind-selector"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <strong style={{ fontSize: '1rem' }}>Do You Want a Photo or a Video?</strong>
          <p className="field-helper" style={{ margin: '2px 0 0 0' }}>
            Pick whether you want Magic Hour to generate a renovated photo or a room video clip.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }} role="group" aria-label="Output format">
          <button
            type="button"
            className={`btn ${selectedKind === 'image' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => {
              setSelectedKind('image');
              scrollToFlowTop();
            }}
            data-testid="select-kind-image"
          >
            Photo (Still Image)
          </button>
          <button
            type="button"
            className={`btn ${selectedKind === 'video' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => {
              setSelectedKind('video');
              scrollToFlowTop();
            }}
            data-testid="select-kind-video"
          >
            Video (Room Clip)
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div>
      <div className="workspace-grid">
        <RoomList
          rooms={project.rooms}
          activeRoomId={activeRoom?.id}
          onSelectRoom={(id) => navigate(`/app/projects/${project.id}/rooms/${id}`)}
          onAddRoom={handleAddRoom}
          canAddRoom={project.rooms.length < 5}
        />

        <section ref={flowTopRef}>
          {activeRoom ? (
            <>
              {/* Initial Setup: Upload Photo + Renovation Brief (disappears once user calculates quote or runs/revises) */}
              {showInitialSetup && (
                <>
                  <RoomViewer room={activeRoom} onUploadPhoto={handleUploadPhoto} />
                  <BriefEditor
                    activeBrief={activeBrief}
                    onSaveBrief={handleSaveBrief}
                    onDraftChange={setDraftBrief}
                  />
                </>
              )}

              {/* Active Quote / Revision Step: Photo vs Video choice + Confirm & Spend (Run It) */}
              {shouldShowQuoteCard && (
                <>
                  {revisionBanner && (
                    <div
                      className="alert alert-success"
                      role="status"
                      data-testid="revision-quote-banner"
                      style={{ marginBottom: '16px' }}
                    >
                      <strong>{revisionBanner}</strong>
                    </div>
                  )}

                  {mediaSelectorCard}

                  {selectedKind === 'image' ? (
                    <QuoteCard
                      kind="image"
                      room={activeRoom}
                      briefRevision={activeBrief}
                      hasUnsavedBrief={Boolean(draftBrief?.isDirty)}
                      onEnsureBriefSaved={handleEnsureBriefSaved}
                      autoQuoteNonce={autoQuoteNonce}
                      onQuoteReady={() => {
                        setHasEnteredQuoteFlow(true);
                        scrollToFlowTop();
                      }}
                      onJobStarted={handleJobStarted}
                    />
                  ) : (
                    <QuoteCard
                      kind="video"
                      room={activeRoom}
                      briefRevision={activeBrief}
                      hasUnsavedBrief={Boolean(draftBrief?.isDirty)}
                      onEnsureBriefSaved={handleEnsureBriefSaved}
                      autoQuoteNonce={autoQuoteNonce}
                      onQuoteReady={() => {
                        setHasEnteredQuoteFlow(true);
                        scrollToFlowTop();
                      }}
                      onJobStarted={handleJobStarted}
                    />
                  )}
                </>
              )}

              {/* Active Loading Step: Generation Progress (only shown while job is running or failed/blocked) */}
              {activeJobId && (isJobRunning || !shouldShowQuoteCard) && (
                <JobTimeline
                  jobId={activeJobId}
                  providerId={
                    jobSnapshot?.provider_id ||
                    (typeof window !== 'undefined'
                      ? localStorage.getItem(`mr_provider_id_${activeJobId}`) || undefined
                      : undefined)
                  }
                  kind={jobSnapshot?.kind || selectedKind}
                  roomId={activeRoom.id}
                  onJobUpdated={handleJobUpdated}
                />
              )}

              {/* Review & Approved Step: Shown right in front of the user when ready_for_review or accepted */}
              {showReviewAndOutput && (
                <>
                  {stillCompareUrl && (
                    <div className="card" style={{ marginBottom: '20px' }}>
                      {activeRoom?.thumbnail_url ? (
                        <ImageCompare
                          beforeUrl={activeRoom.thumbnail_url}
                          afterUrl={stillCompareUrl}
                          roomName={activeRoom.name}
                        />
                      ) : (
                        <div style={{ textAlign: 'center', padding: '16px' }}>
                          <h3 style={{ marginTop: 0 }}>Renovated Photo</h3>
                          <img
                            src={stillCompareUrl}
                            alt={activeRoom?.name || 'Renovated Room'}
                            style={{ maxWidth: '100%', maxHeight: '520px', borderRadius: '8px', objectFit: 'contain' }}
                          />
                        </div>
                      )}
                      {stillReviewAssetId ? (
                        <ReviewChecklist
                          assetId={stillReviewAssetId}
                          kind="image"
                          onReviewed={handleReviewed}
                        />
                      ) : (
                        <div style={{ marginTop: '14px' }}>
                          {isCurrentOutputApproved && activeRoom.accepted_image_asset_id && (
                            <div style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                              <span className="badge badge-connected" data-testid="still-accepted-badge">
                                Photo Approved — Ready to Download Below (Video Unlocked)
                              </span>
                            </div>
                          )}
                          <form
                            onSubmit={async (e) => {
                              e.preventDefault();
                              if (!quickPhotoReviseNotes.trim() || revisingPhoto) return;
                              setRevisingPhoto(true);
                              try {
                                await handleQuickRevise(
                                  quickPhotoReviseNotes.trim(),
                                  'image',
                                  stillAssetId || undefined
                                );
                                setQuickPhotoReviseNotes('');
                              } finally {
                                setRevisingPhoto(false);
                              }
                            }}
                            style={{
                              padding: '12px',
                              borderRadius: '8px',
                              background: 'var(--surface-subtle)',
                              border: '1px solid var(--border)',
                              display: 'flex',
                              gap: '8px',
                              flexWrap: 'wrap',
                              alignItems: 'center',
                            }}
                          >
                            <input
                              type="text"
                              className="text-input"
                              style={{ flex: '1 1 240px' }}
                              placeholder="Want to revise this photo? Describe changes and recalculate credit quote…"
                              value={quickPhotoReviseNotes}
                              onChange={(e) => setQuickPhotoReviseNotes(e.target.value)}
                              data-testid="quick-revise-image-input"
                            />
                            <button
                              type="submit"
                              className="btn btn-secondary"
                              disabled={revisingPhoto || !quickPhotoReviseNotes.trim()}
                              data-testid="quick-revise-image-btn"
                            >
                              {revisingPhoto ? 'Recalculating…' : 'Send Revision & Recalculate Quote'}
                            </button>
                          </form>
                        </div>
                      )}
                    </div>
                  )}

                  {videoClipUrl && videoClipAssetId && (
                    <VideoReview
                      clipAssetId={videoClipAssetId}
                      clipUrl={videoClipUrl}
                      approvedStillUrl={activeRoom.accepted_image_url || stillCompareUrl}
                      roomName={activeRoom.name}
                      isAccepted={Boolean(isCurrentOutputApproved && activeRoom.accepted_clip_asset_id === videoClipAssetId)}
                      canReview={canReviewVideo}
                      onReviewed={handleReviewed}
                      onQuickRevise={handleQuickRevise}
                    />
                  )}

                  {/* End-of-page Approved Download Section + Next Format Selector */}
                  {isCurrentOutputApproved && (
                    <>
                      <section
                        className="card"
                        aria-labelledby="approved-download-heading"
                        data-testid="approved-download-section"
                        style={{
                          marginBottom: '20px',
                          background: 'var(--success-bg)',
                          borderColor: 'var(--success-border)',
                        }}
                      >
                        <h3 id="approved-download-heading" style={{ margin: '0 0 6px', color: 'var(--success-text)' }}>
                          5. Approved — Download Your Renovation Output
                        </h3>
                        <p style={{ margin: '0 0 14px', color: 'var(--success-text)', fontSize: '0.95rem' }}>
                          You approved of your generated renovation output! You can now download your files below.
                        </p>
                        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                          {activeRoom.accepted_image_url && (
                            <a
                              href={`${activeRoom.accepted_image_url}&download=1`}
                              download={`${activeRoom.name.toLowerCase().replace(/\s+/g, '_')}_renovated_photo.jpg`}
                              className="btn btn-primary"
                              data-testid="download-approved-photo"
                            >
                              Download Approved Photo (.jpg)
                            </a>
                          )}
                          {activeRoom.accepted_clip_url && (
                            <a
                              href={`${activeRoom.accepted_clip_url}&download=1`}
                              download={`${activeRoom.name.toLowerCase().replace(/\s+/g, '_')}_renovated_video.mp4`}
                              className="btn btn-primary"
                              data-testid="download-approved-video"
                            >
                              Download Approved Video (.mp4)
                            </a>
                          )}
                        </div>
                      </section>

                      {mediaSelectorCard}
                    </>
                  )}

                  {hasAnyAcceptedClip && (
                    <ClipOrderer
                      rooms={project.rooms}
                      initialTitle={`${project.name} Presentation`}
                      isAssembling={isAssembling}
                      onAssemble={handleAssemblePresentation}
                    />
                  )}

                  <ExportPanel exportData={exportData} onRefresh={handleRefreshExport} />
                </>
              )}
            </>
          ) : (
            <div className="card">Add a room on the left to begin.</div>
          )}
        </section>
      </div>
    </div>
  );
}
