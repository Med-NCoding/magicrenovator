import React, { useEffect, useState } from 'react';

export function PhotoInput({
  onUpload,
  disabled = false,
}: {
  onUpload: (file: File) => Promise<void>;
  disabled?: boolean;
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileSizeText, setFileSizeText] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const choose = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    const nextUrl = URL.createObjectURL(file);
    setPreviewUrl(nextUrl);
    setFileSizeText(`${(file.size / 1024).toFixed(1)} KB`);
    setUploading(true);
    try {
      await onUpload(file);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <p className="field-helper">
        Upload a clear, wide photo of the room showing the floor, walls, and features you want to keep.
      </p>
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        <label className="btn btn-primary">
          Upload Photo
          <input
            data-testid="room-photo-input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={choose}
            disabled={disabled || uploading}
            style={{ display: 'none' }}
          />
        </label>
      </div>
      {fileSizeText && (
        <p className="field-helper" aria-live="polite">
          {uploading ? `Uploading (${fileSizeText})…` : `Uploaded photo (${fileSizeText})`}
        </p>
      )}
    </div>
  );
}
