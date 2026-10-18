import { useState } from "react";

export function avatarId(seat, presets = {}) {
  return seat?.avatar_id || presets[seat?.model?.trim().toLowerCase()] || null;
}

export function Avatar({ seat, presets, fallback, className = "", size }) {
  const id = avatarId(seat, presets);
  const [failed, setFailed] = useState(null);
  return <span className={`agent-avatar ${className}`} style={size ? { "--avatar-size": `${size}px` } : undefined} aria-hidden="true">
    {id && failed !== id ? <img src={`/api/avatars/${id}`} alt="" decoding="async" onError={() => setFailed(id)} /> : <span>{fallback ?? seat?.seat_id ?? seat?.name?.slice(0, 1) ?? "A"}</span>}
  </span>;
}
