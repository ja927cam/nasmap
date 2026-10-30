import { useCallback, useEffect, useRef, useState } from 'react';
import { api, authedBlob } from '../api/client';
import type { Attachment } from '../api/types';
import Icon from './Icon';
import { Modal, formatBytes } from './ui';

const ACCEPT =
  'image/jpeg,image/tiff,image/png,image/webp,image/x-fujifilm-raf,' +
  '.jpg,.JPG,.jpeg,.JPEG,.jfif,.JFIF,.tif,.TIF,.tiff,.TIFF,.png,.PNG,.webp,.WEBP,.raf,.RAF,' +
  '.pdf,.txt,.md,.csv,.json,.mp4,.m4v,.mov,.webm,.mkv,.mp3,.m4a,.wav,.ogg,.glb,.gltf';

export default function AttachmentGallery({
  featureId,
  editable,
  onChanged,
}: {
  featureId: string;
  editable: boolean;
  onChanged?: () => void;
}) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [lightbox, setLightbox] = useState<{ attachment: Attachment; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    async function load() {
      try {
        const items = await api<Attachment[]>(`/features/${featureId}/attachments`);
        if (!active) return;
        setAttachments(items);
        const next: Record<string, string> = {};
        await Promise.all(
          items
            .filter((item) => item.content_type.startsWith('image/'))
            .map(async (item) => {
              const blob = await authedBlob(item.thumb_url);
              if (!active) return;
              const url = URL.createObjectURL(blob);
              urls.push(url);
              next[item.id] = url;
            }),
        );
        if (active) setThumbs(next);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Could not load photos');
      }
    }
    void load();
    return () => {
      active = false;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [featureId, refresh]);

  useEffect(() => {
    return () => {
      if (lightbox) URL.revokeObjectURL(lightbox.url);
    };
  }, [lightbox]);

  const images = attachments.filter((item) => item.content_type.startsWith('image/'));
  const files = attachments.filter((item) => !item.content_type.startsWith('image/'));
  const primary = images[0];

  const openFull = useCallback(
    async (attachment: Attachment) => {
      try {
        const blob = await authedBlob(attachment.content_url);
        const url = URL.createObjectURL(blob);
        setLightbox({ attachment, url });
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not load photo');
      }
    },
    [],
  );

  async function addPhotos(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      Array.from(files).forEach((file) => form.append('files', file));
      const result = await api<{ attachments: Attachment[]; skipped: { filename: string; reason: string }[] }>(
        `/features/${featureId}/attachments`,
        { method: 'POST', body: form },
      );
      if (result.skipped.length) {
        setError(result.skipped.map((item) => `${item.filename}: ${item.reason}`).join(' · '));
      }
      setRefresh((value) => value + 1);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add photo');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  async function downloadAttachment(attachment: Attachment) {
    try {
      const blob = await authedBlob(attachment.content_url);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = attachment.filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not download file');
    }
  }

  async function removePhoto(attachment: Attachment) {
    if (!window.confirm('Remove this attachment from the feature? Uploaded copies are deleted; original server/NAS files are left in place.')) return;
    try {
      await api(`/attachments/${attachment.id}`, { method: 'DELETE' });
      setLightbox(null);
      setRefresh((value) => value + 1);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove photo');
    }
  }

  if (!attachments.length && !editable) return null;

  return (
    <div className="attachment-gallery">
      <div className="attachment-head">
        <h3>Attachments {attachments.length > 0 ? `(${attachments.length})` : ''}</h3>
        {editable && (
          <>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              multiple
              className="hidden-input"
              onChange={(e) => void addPhotos(e.target.files)}
            />
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
            >
              {busy ? 'Adding…' : 'Add file'}
            </button>
          </>
        )}
      </div>

      {primary ? (
        <button type="button" className="photo-primary" onClick={() => void openFull(primary)}>
          {thumbs[primary.id] ? (
            <img src={thumbs[primary.id]} alt={primary.filename} />
          ) : (
            <span>Loading photo…</span>
          )}
          <span className="photo-caption">
            {primary.filename} · {formatBytes(primary.size_bytes)}
          </span>
        </button>
      ) : files.length === 0 ? (
        <p className="hint">No attachments on this feature.</p>
      ) : null}

      {files.length > 0 && (
        <div className="media-list">
          {files.map((attachment) => (
            <div key={attachment.id} className="media-row">
              <Icon name="file" size={15} />
              <div className="grow">
                <strong>{attachment.filename}</strong>
                <small>{attachment.content_type} · {formatBytes(attachment.size_bytes)}</small>
              </div>
              <button
                className="btn btn-ghost btn-xs"
                onClick={() => void downloadAttachment(attachment)}
              >
                Download
              </button>
              {editable && (
                <button
                  className="btn btn-ghost btn-xs danger"
                  onClick={() => void removePhoto(attachment)}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {images.length > 1 && (
        <div className="thumb-grid">
          {images.slice(1).map((attachment) => (
            <button
              key={attachment.id}
              type="button"
              className="thumb"
              onClick={() => void openFull(attachment)}
              title={attachment.filename}
            >
              {thumbs[attachment.id] ? (
                <img src={thumbs[attachment.id]} alt={attachment.filename} />
              ) : (
                <span className="thumb-placeholder">{attachment.filename}</span>
              )}
            </button>
          ))}
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      {lightbox && (
        <Modal title={lightbox.attachment.filename} onClose={() => setLightbox(null)} wide>
          <img className="lightbox-image" src={lightbox.url} alt={lightbox.attachment.filename} />
          <div className="button-row end">
            {editable && (
              <button className="btn btn-danger btn-sm" onClick={() => void removePhoto(lightbox.attachment)}>
                Remove photo
              </button>
            )}
            <a className="btn btn-secondary btn-sm" href={lightbox.url} download={lightbox.attachment.filename}>
              Download
            </a>
          </div>
        </Modal>
      )}
    </div>
  );
}
