import { useEffect, useRef, useState } from 'react';
import { Camera, Check, Eye, FileText, LoaderCircle, RefreshCw, Trash2, Upload } from 'lucide-react';
import { api } from '../api';

// Mirrors the backend limits in app/engine/artifact_retrieval.py; the server
// re-validates type, file signature and size regardless of what happens here.
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'application/pdf'];
export const MAX_FILE_BYTES = 5 * 1024 * 1024;

const TEXT = {
  en: {
    choose: 'Choose document source', device: 'Upload from device', camera: 'Take a picture', cancel: 'Cancel',
    hint: 'JPG, PNG or PDF, up to 5 MB.', capture: 'Capture', retake: 'Retake', replace: 'Replace', remove: 'Remove',
    view: 'View', confirm: 'Confirm & upload', uploading: 'Uploading…', preview: 'Preview',
    cameraError: 'The camera could not be started. You can upload a file from your device instead.',
    badType: 'This file type is not supported. Please choose a JPG, PNG or PDF file.',
    tooLarge: 'This file is larger than 5 MB. Please choose a smaller file.', failed: 'Upload failed.',
  },
  mr: {
    choose: 'दस्तऐवजाचा स्रोत निवडा', device: 'डिव्हाइसवरून अपलोड करा', camera: 'फोटो काढा', cancel: 'रद्द करा',
    hint: 'JPG, PNG किंवा PDF, ५ MB पर्यंत.', capture: 'फोटो घ्या', retake: 'पुन्हा फोटो काढा', replace: 'बदला', remove: 'काढून टाका',
    view: 'पहा', confirm: 'पुष्टी करा व अपलोड करा', uploading: 'अपलोड होत आहे…', preview: 'पूर्वावलोकन',
    cameraError: 'कॅमेरा सुरू करता आला नाही. आपण डिव्हाइसवरून फाइल अपलोड करू शकता.',
    badType: 'हा फाइल प्रकार समर्थित नाही. कृपया JPG, PNG किंवा PDF फाइल निवडा.',
    tooLarge: 'ही फाइल ५ MB पेक्षा मोठी आहे. कृपया लहान फाइल निवडा.', failed: 'अपलोड अयशस्वी झाले.',
  },
};

function formatSize(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

// Choose source -> upload / capture -> preview -> confirm. Nothing is sent to
// the server until the citizen confirms; the consent/ownership checks are the
// existing upload endpoint's.
export default function DocumentUploader({ applicationId, requirementCode, title, language = 'en', replacing = false, initialSource = null, onUploaded, onCancel }) {
  const t = TEXT[language] || TEXT.en;
  const [stage, setStage] = useState('choose'); // choose | camera | preview
  const [selection, setSelection] = useState(null); // { file, source, url }
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const deviceInput = useRef(null);
  const captureInput = useRef(null);
  const video = useRef(null);
  const stream = useRef(null);
  const cameraSupported = typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia);

  function stopCamera() {
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
  }

  // Opened straight from the card's "Upload document" / "Take photo" button:
  // go directly to that source (the choice stays available if it is dismissed).
  useEffect(() => {
    if (initialSource === 'camera') openCamera();
    else if (initialSource === 'device') deviceInput.current?.click();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Unmount only: release the camera and the preview's object URL.
  const previewUrl = useRef(null);
  useEffect(() => () => {
    stopCamera();
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
  }, []);

  function accept(file, source) {
    setError(null);
    if (!file) return;
    if (!ACCEPTED_TYPES.includes(file.type)) { setError(t.badType); return; }
    if (file.size > MAX_FILE_BYTES) { setError(t.tooLarge); return; }
    const url = URL.createObjectURL(file);
    previewUrl.current = url;
    setSelection({ file, source, url });
    setStage('preview');
  }

  async function openCamera() {
    setError(null);
    if (!cameraSupported) { captureInput.current?.click(); return; }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      setStage('camera');
    } catch {
      setError(t.cameraError);
    }
  }

  useEffect(() => {
    if (stage === 'camera' && video.current && stream.current) {
      video.current.srcObject = stream.current;
      video.current.play?.()?.catch?.(() => {});
    }
  }, [stage]);

  function capturePhoto() {
    const element = video.current;
    const canvas = document.createElement('canvas');
    canvas.width = element?.videoWidth || 1280;
    canvas.height = element?.videoHeight || 720;
    canvas.getContext('2d')?.drawImage(element, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(blob => {
      stopCamera();
      if (!blob) { setError(t.cameraError); setStage('choose'); return; }
      accept(new File([blob], 'camera-capture.jpg', { type: 'image/jpeg' }), 'camera');
    }, 'image/jpeg', 0.9);
  }

  function discardSelection() {
    if (selection?.url) URL.revokeObjectURL(selection.url);
    previewUrl.current = null;
    setSelection(null);
    setStage('choose');
  }

  function replaceSelection() {
    const source = selection?.source;
    discardSelection();
    if (source === 'camera') openCamera(); else deviceInput.current?.click();
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const content = await readAsBase64(selection.file);
      const updated = await api.uploadRequirement(applicationId, requirementCode, {
        title, contentType: selection.file.type, content, fileName: selection.file.name,
      });
      discardSelection();
      onUploaded?.(updated);
    } catch (err) {
      setError(err.message || t.failed);
      // A timed-out upload may still have been stored: if it was, finish as
      // a normal success instead of asking the citizen to upload again.
      // (When replacing an earlier upload the two cannot be told apart, so
      // the message alone is shown.)
      if (err.outcomeUnknown && !replacing) {
        api.application(applicationId).then(current => {
          const saved = (current?.requirements || []).find(item => item.requirementCode === requirementCode);
          if (saved?.status === 'VALIDATED' && saved.documentId) { discardSelection(); onUploaded?.(current); }
        }).catch(() => {});
      }
    } finally {
      setBusy(false);
    }
  }

  const isImage = selection?.file.type.startsWith('image/');

  return (
    <div className="upload-form document-uploader">
      <input ref={deviceInput} type="file" hidden accept={ACCEPTED_TYPES.join(',')} data-testid="device-input"
        onChange={event => { accept(event.target.files?.[0], 'device'); event.target.value = ''; }} />
      <input ref={captureInput} type="file" hidden accept="image/*" capture="environment" data-testid="camera-input"
        onChange={event => { accept(event.target.files?.[0], 'camera'); event.target.value = ''; }} />
      {error && <div className="alert danger" role="alert">{error}</div>}

      {stage === 'choose' && (
        <>
          <b>{t.choose}</b>
          <small className="muted">{t.hint}</small>
          <div className="upload-sources">
            <button type="button" className="upload-source" onClick={() => deviceInput.current?.click()}><Upload size={22} aria-hidden="true" />{t.device}</button>
            <button type="button" className="upload-source" onClick={openCamera}><Camera size={22} aria-hidden="true" />{t.camera}</button>
          </div>
          <div className="actions"><button type="button" className="link" onClick={onCancel}>{t.cancel}</button></div>
        </>
      )}

      {stage === 'camera' && (
        <>
          <video ref={video} className="camera-view" autoPlay playsInline muted aria-label={t.camera} />
          <div className="actions">
            <button type="button" className="outline" onClick={() => { stopCamera(); setStage('choose'); }}>{t.cancel}</button>
            <button type="button" className="primary button-with-icon" onClick={capturePhoto}><Camera size={18} aria-hidden="true" />{t.capture}</button>
          </div>
        </>
      )}

      {stage === 'preview' && selection && (
        <>
          <b>{t.preview}</b>
          {isImage
            ? <img className="upload-preview-image" src={selection.url} alt={`${t.preview}: ${selection.file.name}`} />
            : <p className="upload-preview-file"><FileText size={20} aria-hidden="true" />PDF · {selection.file.name}</p>}
          <small className="muted">{selection.file.name} · {formatSize(selection.file.size)}</small>
          <div className="actions">
            <button type="button" className="outline button-with-icon" onClick={() => window.open(selection.url, '_blank', 'noopener')}><Eye size={18} aria-hidden="true" />{t.view}</button>
            <button type="button" className="outline button-with-icon" disabled={busy} onClick={replaceSelection}>{selection.source === 'camera' ? <Camera size={18} aria-hidden="true" /> : <RefreshCw size={18} aria-hidden="true" />}{selection.source === 'camera' ? t.retake : t.replace}</button>
            <button type="button" className="outline button-with-icon" disabled={busy} onClick={discardSelection}><Trash2 size={18} aria-hidden="true" />{t.remove}</button>
            <button type="button" className="primary button-with-icon" disabled={busy} onClick={confirm}>{busy ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Check size={18} aria-hidden="true" />}{busy ? t.uploading : t.confirm}</button>
          </div>
        </>
      )}
    </div>
  );
}
