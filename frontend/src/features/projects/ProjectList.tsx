import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiClient, SafeAppClientError } from '../../api/client';
import { ProjectSummary } from '../../api/types';
import { useAppContext } from '../../app/providers';

const STORAGE_PROJECTS_KEY = 'mr_saved_projects_v2';

function loadSavedProjects(): ProjectSummary[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_PROJECTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveProjectsToStorage(items: ProjectSummary[]) {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_PROJECTS_KEY, JSON.stringify(items));
  } catch {}
}

export function ProjectList() {
  const { connection, openConnectModal } = useAppContext();
  const [projects, setProjects] = useState<ProjectSummary[]>(() => loadSavedProjects());
  const [newProjectName, setNewProjectName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await apiClient.listProjects();
        if (!active) return;
        const stored = loadSavedProjects();
        const mergedMap = new Map<string, ProjectSummary>();
        for (const p of stored) mergedMap.set(p.id, p);
        for (const p of res.items || []) mergedMap.set(p.id, p);
        const merged = Array.from(mergedMap.values());
        setProjects(merged);
        saveProjectsToStorage(merged);
      } catch {
        // Keep local projects on network/cold-start
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [connection?.checked_at, connection?.connected]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newProjectName.trim();
    if (!trimmed) return;
    if (!connection?.connected) {
      openConnectModal();
    }
    setError(null);
    try {
      const created = await apiClient.createProject(trimmed);
      const updated = [created, ...projects.filter((p) => p.id !== created.id)];
      setProjects(updated);
      saveProjectsToStorage(updated);
      localStorage.setItem(`mr_project_name_${created.id}`, trimmed);
      setNewProjectName('');
      navigate(`/app/projects/${created.id}`);
    } catch (err) {
      setError(err instanceof SafeAppClientError ? err.message : 'Failed to create project.');
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    const updated = projects.filter((p) => p.id !== projectId);
    setProjects(updated);
    saveProjectsToStorage(updated);
    try {
      await apiClient.deleteProject(projectId);
    } catch {
      // Already removed locally
    }
  };

  return (
    <main style={{ padding: '24px', maxWidth: '880px', margin: '0 auto', width: '100%' }}>
      <div className="card" style={{ marginBottom: '24px' }}>
        <h1 style={{ marginTop: 0 }}>Start a Renovation Project</h1>
        <p className="field-helper">
          Name your project (e.g., Dorm, Bedroom, Apartment), attach a photo, write your prompt, and generate directly with Magic Hour.
        </p>
        <form onSubmit={handleCreateProject} style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 280px' }}>
            <label htmlFor="new-project-name" className="field-label">
              Project name
            </label>
            <input
              id="new-project-name"
              type="text"
              className="text-input"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              placeholder="e.g., Dorm"
              required
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button type="submit" className="btn btn-primary">
              Create Project
            </button>
          </div>
        </form>
      </div>

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '16px' }}>
          {error}
        </div>
      )}

      {loading && projects.length === 0 ? (
        <div className="card" aria-live="polite">
          Loading projects…
        </div>
      ) : projects.length === 0 ? (
        <div className="card">
          <p style={{ margin: 0 }}>No projects yet. Type a name above (like &ldquo;Dorm&rdquo;) and click Create Project to start.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '14px' }}>
          {projects.map((p) => (
            <div
              key={p.id}
              className="card"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}
            >
              <div>
                <h2 style={{ margin: 0, fontSize: '1.2rem' }}>{p.name}</h2>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <Link to={`/app/projects/${p.id}`} className="btn btn-primary">
                  Open Project
                </Link>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => void handleDeleteProject(p.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
