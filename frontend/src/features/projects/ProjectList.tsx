import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiClient, SafeAppClientError } from '../../api/client';
import { ProjectSummary } from '../../api/types';
import { useAppContext } from '../../app/providers';

export function ProjectList() {
  const { connection, openConnectModal } = useAppContext();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [newProjectName, setNewProjectName] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const loadProjects = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listProjects();
      setProjects(res.items);
    } catch (err) {
      setError(err instanceof SafeAppClientError ? err.message : 'Failed to load projects.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, [connection?.checked_at, connection?.masked_key, connection?.connected]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    if (!connection?.connected) {
      openConnectModal();
    }
    try {
      const created = await apiClient.createProject(newProjectName.trim());
      setNewProjectName('');
      const room = await apiClient.createRoom(created.id, 'Kitchen', 'kitchen', 0);
      navigate(`/app/projects/${created.id}/rooms/${room.id}`);
    } catch (err) {
      setError(err instanceof SafeAppClientError ? err.message : 'Failed to create project.');
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    try {
      await apiClient.deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch (err) {
      setError(err instanceof SafeAppClientError ? err.message : 'Failed to delete project.');
    }
  };

  return (
    <main style={{ padding: '24px', maxWidth: '1000px', margin: '0 auto', width: '100%' }}>
      <div className="card" style={{ marginBottom: '24px' }}>
        <h1 style={{ marginTop: 0 }}>Start a Renovation Project</h1>
        <p className="field-helper">
          Create a project to upload your room photo, describe your renovation, choose photo or video output, and download your approved result.
        </p>
        <form onSubmit={handleCreateProject} style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 280px' }}>
            <label htmlFor="new-project-name" className="field-label">
              New project name
            </label>
            <input
              id="new-project-name"
              type="text"
              className="text-input"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              placeholder="e.g., Main Floor Remodel"
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
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="card" aria-live="polite">
          Loading projects…
        </div>
      ) : projects.length === 0 ? (
        <div className="card">
          <p>No projects yet. Create a project above to begin.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '16px' }}>
          {projects.map((p) => {
            const firstRoom = p.rooms[0];
            const targetUrl = firstRoom
              ? `/app/projects/${p.id}/rooms/${firstRoom.id}`
              : `/app/projects/${p.id}`;
            return (
              <div
                key={p.id}
                className="card"
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h2 style={{ margin: 0, fontSize: '1.25rem' }}>{p.name}</h2>
                  </div>
                  <p className="field-helper" style={{ marginBottom: 0 }}>
                    {p.room_count} {p.room_count === 1 ? 'room' : 'rooms'} · Expires {new Date(p.expires_at).toLocaleDateString()}
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <Link to={targetUrl} className="btn btn-primary">
                    Open Workspace
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
            );
          })}
        </div>
      )}
    </main>
  );
}
