import { useEffect, useRef, useState } from "react";

const SIZE = 280;
const INITIAL = { x: 0, y: 0, zoom: 1, rotation: 0 };

function geometry(image, crop) {
  const swapped = crop.rotation % 180 !== 0;
  const width = swapped ? image.height : image.width;
  const height = swapped ? image.width : image.height;
  const scale = Math.max(SIZE / width, SIZE / height) * crop.zoom;
  const maxX = (width * scale - SIZE) / 2;
  const maxY = (height * scale - SIZE) / 2;
  return { scale, x: Math.max(-maxX, Math.min(maxX, crop.x)), y: Math.max(-maxY, Math.min(maxY, crop.y)) };
}

function draw(canvas, image, crop) {
  const { scale, x, y } = geometry(image, crop);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.scale(canvas.width / SIZE, canvas.height / SIZE);
  ctx.translate(SIZE / 2 + x, SIZE / 2 + y);
  ctx.rotate(crop.rotation * Math.PI / 180);
  ctx.drawImage(image, -image.width * scale / 2, -image.height * scale / 2, image.width * scale, image.height * scale);
  ctx.restore();
}

export function AvatarEditor({ onSave, onCancel, label = "保存头像" }) {
  const [image, setImage] = useState(null);
  const [crop, setCrop] = useState(INITIAL);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canvas = useRef(null);
  const preview = useRef(null);
  const drag = useRef(null);
  const requestId = useRef(0);
  useEffect(() => () => { requestId.current += 1; }, []);
  useEffect(() => {
    if (!image) return;
    draw(canvas.current, image, crop);
    draw(preview.current, image, crop);
  }, [image, crop]);

  const choose = async file => {
    const id = ++requestId.current;
    if (!file) return;
    setError("");
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 10_000_000) {
      setError("请选择 10 MB 以内的 PNG、JPEG 或 WebP 图片");
      return;
    }
    const url = URL.createObjectURL(file);
    try {
      const next = new Image();
      next.src = url;
      await next.decode();
      if (id === requestId.current) { setImage(next); setCrop(INITIAL); }
    } catch { if (id === requestId.current) setError("图片无法读取，请换一张图片"); }
    finally { URL.revokeObjectURL(url); }
  };
  const move = (x, y) => setCrop(current => {
    const position = geometry(image, { ...current, x, y });
    return { ...current, x: position.x, y: position.y };
  });
  const save = async () => {
    if (!image || busy) return;
    setBusy(true); setError("");
    try {
      const output = document.createElement("canvas");
      output.width = output.height = 256;
      draw(output, image, crop);
      await onSave(output.toDataURL("image/png"));
    } catch (err) { setError(err.message || "头像保存失败，请重试"); }
    finally { setBusy(false); }
  };

  return <div className="avatar-editor" aria-busy={busy}>
    <label className="avatar-upload" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!busy) choose(event.dataTransfer.files[0]); }}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4" /><circle cx="8" cy="8" r="1.5" /><path d="m4 17 5-5 4 4 3-3 5 5" /></svg>
      <span>{image ? "更换图片" : "上传图片或拖放到这里"}<small>PNG、JPEG、WebP · 最大 10 MB</small></span>
      <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择头像图片" disabled={busy} onChange={event => { choose(event.target.files[0]); event.target.value = ""; }} />
    </label>
    {image && <>
      <div className="avatar-crop-layout">
        <div className="avatar-crop-area">
          <canvas ref={canvas} width={SIZE} height={SIZE} tabIndex={0} role="img" aria-label="头像裁剪区域，拖动或用方向键移动图片" onPointerDown={event => {
            event.currentTarget.focus(); event.currentTarget.setPointerCapture(event.pointerId);
            const current = geometry(image, crop);
            drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, offsetX: current.x, offsetY: current.y };
          }} onPointerMove={event => {
            const start = drag.current;
            if (!start || start.pointerId !== event.pointerId) return;
            const ratio = SIZE / event.currentTarget.getBoundingClientRect().width;
            move(start.offsetX + (event.clientX - start.x) * ratio, start.offsetY + (event.clientY - start.y) * ratio);
          }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }} onKeyDown={event => {
            const delta = { ArrowLeft: [-5, 0], ArrowRight: [5, 0], ArrowUp: [0, -5], ArrowDown: [0, 5] }[event.key];
            if (delta) { event.preventDefault(); const current = geometry(image, crop); move(current.x + delta[0], current.y + delta[1]); }
          }} />
          <div className="avatar-crop-mask" aria-hidden="true" />
        </div>
        <div className="avatar-preview"><canvas ref={preview} width="80" height="80" aria-label="头像预览" role="img" /><span>头像预览</span></div>
      </div>
      <p className="subtle avatar-crop-hint">拖动调整位置，也可使用方向键微调。</p>
      <label className="avatar-zoom">缩放 <output>{crop.zoom.toFixed(1)}×</output><input aria-label="头像缩放" type="range" min="1" max="3" step="0.05" value={crop.zoom} onChange={event => setCrop(current => ({ ...current, zoom: Number(event.target.value) }))} /></label>
      <div className="avatar-tools"><button type="button" className="button button-quiet" onClick={() => setCrop(current => ({ ...INITIAL, rotation: (current.rotation + 90) % 360 }))}>旋转 90°</button><button type="button" className="button button-quiet" onClick={() => setCrop(INITIAL)}>重置裁剪</button></div>
    </>}
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="avatar-actions"><button type="button" className="button button-quiet" onClick={onCancel} disabled={busy}>取消</button><button type="button" className="button button-primary" onClick={save} disabled={!image || busy}>{busy ? "正在保存…" : label}</button></div>
  </div>;
}
