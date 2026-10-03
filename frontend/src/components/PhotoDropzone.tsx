"use client";

import { useEffect, useId, useRef, useState } from "react";

export const MAX_PHOTOS = 4;
export const MAX_PHOTO_MB = 5;
const ACCEPT = ["image/jpeg", "image/png", "image/webp"];
const EXTENSIONS = /\.(jpe?g|png|webp)$/i;

export interface PhotoItem {
  id: string;
  file: File;
  previewUrl: string;
  status: "ready" | "uploading" | "done" | "error";
  progress: number; // 0..1
  error?: string;
}

interface Props {
  photos: PhotoItem[];
  onChange: (photos: PhotoItem[]) => void;
  disabled?: boolean;
}

/** Custom photo picker: click/keyboard, drag & drop, camera (mobile), previews, per-photo progress. */
export function PhotoDropzone({ photos, onChange, disabled = false }: Props) {
  const ids = { input: useId(), camera: useId(), help: useId(), errors: useId() };
  const inputRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [canCapture, setCanCapture] = useState(false);
  const latest = useRef(photos);
  latest.current = photos;

  useEffect(() => {
    setCanCapture(window.matchMedia?.("(pointer: coarse)").matches ?? false);
    // Revoke object URLs when the component goes away
    return () => latest.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
  }, []);

  function addFiles(list: FileList | File[] | null) {
    if (!list || disabled) return;
    const problems: string[] = [];
    const next = [...photos];
    for (const file of Array.from(list)) {
      const typeOk = ACCEPT.includes(file.type) || (!file.type && EXTENSIONS.test(file.name));
      if (!typeOk) {
        problems.push(`"${file.name}" isn't a supported image. Use JPG, PNG or WebP.`);
      } else if (file.size > MAX_PHOTO_MB * 1024 * 1024) {
        problems.push(`"${file.name}" is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is ${MAX_PHOTO_MB} MB per photo.`);
      } else if (next.length >= MAX_PHOTOS) {
        problems.push(`Only ${MAX_PHOTOS} photos are allowed, so "${file.name}" was not added.`);
      } else {
        next.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, file, previewUrl: URL.createObjectURL(file),
          status: "ready", progress: 0 });
      }
    }
    setErrors(problems);
    onChange(next);
  }

  function remove(id: string) {
    const p = photos.find((x) => x.id === id);
    if (p) URL.revokeObjectURL(p.previewUrl);
    setErrors([]);
    onChange(photos.filter((x) => x.id !== id));
  }

  const full = photos.length >= MAX_PHOTOS;
  const openPicker = () => !disabled && !full && inputRef.current?.click();

  return (
    <div>
      <p className="label" id={`${ids.input}-label`}>Photos <span className="font-normal text-slate-500">(recommended)</span></p>
      <input ref={inputRef} id={ids.input} type="file" accept={ACCEPT.join(",")} multiple className="sr-only" tabIndex={-1}
        aria-hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      <input ref={cameraRef} id={ids.camera} type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1}
        aria-hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />

      <div
        onDragEnter={(e) => { e.preventDefault(); if (!disabled) setDragging(true); }}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = full || disabled ? "none" : "copy"; }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
        className={`rounded-2xl border-2 border-dashed p-4 transition ${dragging ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50/60"} ${disabled ? "opacity-70" : ""}`}
      >
        {photos.length === 0 ? (
          <button type="button" onClick={openPicker} disabled={disabled} aria-describedby={`${ids.help} ${ids.errors}`}
            className="flex w-full flex-col items-center gap-2 rounded-xl px-4 py-8 text-center outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
            <span className="grid h-12 w-12 place-items-center rounded-full bg-brand-100 text-brand-600"><UploadIcon /></span>
            <span className="text-sm font-semibold text-slate-900">Upload photos</span>
            <span className="text-sm text-slate-600">Drag &amp; drop or click to browse</span>
            <span id={ids.help} className="text-xs text-slate-500">Up to {MAX_PHOTOS} photos • {MAX_PHOTO_MB} MB each • JPG, PNG or WebP</span>
          </button>
        ) : (
          <div>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Selected photos">
              {photos.map((p, i) => (
                <li key={p.id} className="group relative aspect-square overflow-hidden rounded-xl border border-slate-200 bg-white">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.previewUrl} alt={`Photo ${i + 1}${i === 0 ? " (primary)" : ""}: ${p.file.name}`} className="h-full w-full object-cover" />
                  {i === 0 && <span className="absolute left-2 top-2 rounded-full bg-brand-600 px-2 py-0.5 text-[10px] font-semibold text-white">Primary</span>}
                  {p.status === "uploading" && (
                    <div className="absolute inset-x-0 bottom-0 bg-black/55 p-2" role="progressbar" aria-label={`Uploading photo ${i + 1}`}
                      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p.progress * 100)}>
                      <div className="h-1.5 rounded-full bg-white/30"><div className="h-1.5 rounded-full bg-white transition-all" style={{ width: `${Math.round(p.progress * 100)}%` }} /></div>
                      <p className="mt-1 text-[10px] text-white">Uploading… {Math.round(p.progress * 100)}%</p>
                    </div>
                  )}
                  {p.status === "done" && <span className="absolute bottom-2 right-2 grid h-6 w-6 place-items-center rounded-full bg-emerald-600 text-xs text-white" aria-label="Uploaded">✓</span>}
                  {p.status === "error" && <p className="absolute inset-x-0 bottom-0 bg-rose-600/90 p-1.5 text-[10px] text-white">{p.error ?? "Upload failed"}</p>}
                  {!disabled && p.status !== "uploading" && p.status !== "done" && (
                    <button type="button" onClick={() => remove(p.id)} aria-label={`Remove photo ${i + 1}`}
                      className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-black/60 text-white opacity-90 transition hover:bg-black/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
                      ✕
                    </button>
                  )}
                </li>
              ))}
              {!full && !disabled && (
                <li>
                  <button type="button" onClick={openPicker} aria-describedby={ids.help}
                    className="flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-slate-300 bg-white text-xs text-slate-600 outline-none hover:border-brand-500 hover:text-brand-700 focus-visible:ring-2 focus-visible:ring-brand-500">
                    <span className="text-xl leading-none" aria-hidden>+</span> Add photo
                  </button>
                </li>
              )}
            </ul>
            <p id={ids.help} className="mt-2 text-xs text-slate-500">
              {photos.length} of {MAX_PHOTOS} photos • {MAX_PHOTO_MB} MB each • the first photo is shown on your listing
            </p>
          </div>
        )}
        {canCapture && !full && !disabled && (
          <button type="button" onClick={() => cameraRef.current?.click()} className="btn-secondary mt-3 w-full sm:w-auto">
            <CameraIcon /> Take a photo
          </button>
        )}
      </div>
      <p className="hint">Location data (GPS/EXIF) is removed from photos automatically.</p>
      <div id={ids.errors} aria-live="assertive">
        {errors.length > 0 && (
          <ul role="alert" className="mt-2 space-y-1 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {errors.map((e) => <li key={e}>{e}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}

function UploadIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m21 15-5-5L5 21" />
    </svg>
  );
}

function CameraIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7h3l2-3h6l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z" /><circle cx="12" cy="13" r="4" />
    </svg>
  );
}
