import { useEffect, useState } from "react";
import { arenaApi } from "../api/arenaClient.js";
import { Avatar, avatarId } from "./Avatar.jsx";
import { AvatarEditor } from "./AvatarEditor.jsx";
import "./avatars.css";

export function AvatarSettings({ snapshot, onNotice, initialSeatId }) {
  const seats = Object.values(snapshot?.seats || {});
  const [seatId, setSeatId] = useState(String(initialSeatId || seats[0]?.seat_id || ""));
  const seat = seats.find(item => String(item.seat_id) === seatId);
  const [seatModel, setSeatModel] = useState(seat?.model || "");
  const [model, setModel] = useState("");
  const [models, setModels] = useState([]);
  const [editor, setEditor] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setSeatModel(seat?.model || ""); }, [seat?.model, seatId]);
  useEffect(() => {
    let active = true;
    arenaApi.avatarModels().then(data => { if (active) setModels(data.models); }).catch(error => onNotice(error.message, true));
    return () => { active = false; };
  }, [onNotice]);
  const suggestions = [...new Set([...seats.map(item => item.model), ...models.map(item => item.model)])];
  const run = async operation => {
    setBusy(true);
    try { await operation(); }
    catch (error) { onNotice(error.message, true); }
    finally { setBusy(false); }
  };
  const saveImage = async dataUrl => {
    const { avatar_id } = await arenaApi.uploadAvatar(dataUrl);
    if (editor.type === "seat") await arenaApi.seatAppearance(editor.seatId, { avatar_id });
    else setModels((await arenaApi.setModelAvatar(editor.model, avatar_id)).models);
    setEditor(null);
    onNotice(editor.type === "seat" ? "席位头像已更新" : "模型默认头像已保存，同模型自动使用");
  };

  if (editor) return <div className="settings-content">
    <h4>{editor.type === "seat" ? `${editor.name} · 专属头像` : `${editor.model} · 模型头像`}</h4>
    <p className="subtle">调整裁剪后保存，图片只保存在本地。</p>
    <AvatarEditor onSave={saveImage} onCancel={() => setEditor(null)} />
  </div>;

  return <div className="settings-content avatar-settings">
    <section className="settings-section">
      <h4>席位头像</h4>
      <label>选择 Agent<select value={seatId} onChange={event => setSeatId(event.target.value)}>{seats.map(item => <option key={item.seat_id} value={item.seat_id}>{item.seat_id} 号位 · {item.name}</option>)}</select></label>
      {seat && <>
        <div className="avatar-identity"><Avatar seat={seat} presets={snapshot.model_avatars} size={64} /><div><strong>{seat.name}</strong><p>{seat.avatar_id ? "使用席位专属头像" : avatarId(seat, snapshot.model_avatars) ? "自动使用模型头像" : "使用席位占位头像"}</p></div></div>
        <div className="avatar-actions"><button type="button" className="button button-primary" disabled={busy} onClick={() => setEditor({ type: "seat", seatId: seat.seat_id, name: seat.name })}>上传专属头像</button>{seat.avatar_id && <button type="button" className="button button-quiet" disabled={busy} onClick={() => run(async () => { await arenaApi.seatAppearance(seat.seat_id, { avatar_id: null }); onNotice("已恢复跟随模型头像"); })}>跟随模型</button>}</div>
        <form className="avatar-model-form" onSubmit={event => { event.preventDefault(); run(async () => { await arenaApi.seatAppearance(seat.seat_id, { model: seatModel }); onNotice("模型名称已更新"); }); }}>
          <label htmlFor="seat-model-name">模型名称<input id="seat-model-name" value={seatModel} maxLength={200} list="avatar-model-names" onChange={event => setSeatModel(event.target.value)} required /></label>
          <button className="button button-quiet" disabled={busy || !seatModel.trim() || seatModel === seat.model}>保存模型</button>
        </form>
      </>}
    </section>
    <section className="settings-section">
      <h4>模型默认头像</h4>
      <p className="subtle">按完整模型名称自动匹配，忽略大小写和首尾空格。新加入、重连和换局后的 Agent 都会沿用已保存的头像。</p>
      <form onSubmit={event => { event.preventDefault(); if (model.trim()) setEditor({ type: "model", model: model.trim() }); }}>
        <label htmlFor="avatar-model-name">配置模型<input id="avatar-model-name" placeholder="例如 gpt-6.1-sol" value={model} maxLength={200} list="avatar-model-names" onChange={event => setModel(event.target.value)} required /></label>
        <button className="button button-primary button-wide" disabled={!model.trim()}>设置模型头像</button>
      </form>
      <datalist id="avatar-model-names">{suggestions.filter(Boolean).map(name => <option value={name} key={name} />)}</datalist>
      <div className="avatar-preset-list">{models.length ? models.map(item => <div className="avatar-preset-row" key={item.model.toLowerCase()}>
        <Avatar seat={item} size={42} fallback={item.model.slice(0, 1).toUpperCase()} /><div className="avatar-preset-name"><strong>{item.model}</strong><span>模型默认</span></div>
        <button type="button" className="text-button" disabled={busy} aria-label={`更换 ${item.model} 头像`} onClick={() => setEditor({ type: "model", model: item.model })}>更换</button>
        <button type="button" className="text-button" disabled={busy} aria-label={`移除 ${item.model} 头像`} onClick={() => run(async () => { setModels((await arenaApi.setModelAvatar(item.model, null)).models); onNotice("模型头像已移除"); })}>移除</button>
      </div>) : <p className="subtle avatar-library-empty">为模型设置一次头像，之后加入的同模型 Agent 会自动沿用。</p>}</div>
    </section>
  </div>;
}
