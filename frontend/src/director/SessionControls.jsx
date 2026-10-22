import { useEffect, useState } from "react";
import { arenaApi } from "../api/arenaClient.js";

export function SessionControls({ snapshot, onNotice }) {
  const [games, setGames] = useState([]);
  const [game, setGame] = useState("");
  const [targets, setTargets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [confirmLoad, setConfirmLoad] = useState(null);
  const [flowText, setFlowText] = useState("");
  const [message, setMessage] = useState("");
  const [recipient, setRecipient] = useState("");
  const [directory, setDirectory] = useState("");
  const [bootstrap, setBootstrap] = useState("");
  const seats = Object.values(snapshot?.seats || {});
  const flow = snapshot?.flow;
  const active = ["RUNNING", "PAUSED", "AWAITING_HOST"].includes(flow?.status);
  const run = async (operation, success) => {
    setBusy(true);
    try { await operation(); if (success) onNotice(success); }
    catch (error) { onNotice(error.message, true); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    let current = true;
    arenaApi.games().then(data => { if (current) setGames(data.games); }).catch(error => { if (current) onNotice(error.message, true); });
    return () => { current = false; };
  }, [onNotice]);
  const exportScenario = () => run(async () => {
    const scenario = await arenaApi.scenario();
    const url = URL.createObjectURL(new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = "arena-scenario.json"; link.click(); URL.revokeObjectURL(url);
  });
  const readScenario = async event => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const scenario = JSON.parse(await file.text());
      if (!scenario.title || !Array.isArray(scenario.seats)) throw new Error("剧本需要标题与席位列表");
      setConfirmLoad(scenario);
    } catch (error) { onNotice(error.message, true); }
  };
  const connectSeat = seats.find(seat => String(seat.seat_id) === recipient);
  const makeBootstrap = () => {
    if (!connectSeat) return;
    const url = `${window.location.origin}/bootstrap/${connectSeat.seat_id}?claim_token=${encodeURIComponent(connectSeat.claim_token)}`;
    setBootstrap(`python -c "import urllib.request;exec(urllib.request.urlopen('${url}').read().decode('utf-8'))"`);
  };
  return <>
    <details className="director-section" open><summary>剧本与自动流程</summary>
      <div className="director-actions"><label className="button button-quiet">导入剧本<input className="sr-only" type="file" accept=".json,application/json" onChange={readScenario} disabled={busy} /></label><button type="button" className="button button-quiet" onClick={exportScenario} disabled={busy}>导出剧本</button></div>
      {confirmLoad && <div className="director-confirm"><p>载入「{confirmLoad.title}」并开始新局，当前局会自动存档。</p><button className="button button-primary" disabled={busy} onClick={() => run(async () => { await arenaApi.loadScenario(confirmLoad); setConfirmLoad(null); }, "剧本已载入")}>确认载入</button><button className="button button-quiet" onClick={() => setConfirmLoad(null)}>取消</button></div>}
      <p className="director-pending">{flow?.status || "IDLE"} · {Math.min(flow?.steps?.length || 0, (flow?.index || 0) + 1)} / {flow?.steps?.length || 0} 步</p>
      <div className="director-actions">
        {!active && <button className="button button-primary" disabled={busy || !flow?.steps?.length} onClick={() => run(() => arenaApi.startFlow(flow.steps), "流程已启动")}>启动剧本流程</button>}
        {active && (flow.status === "PAUSED" ? <button className="button button-primary" disabled={busy} onClick={() => run(() => arenaApi.flowControl("resume"))}>继续流程</button> : <button className="button button-quiet" disabled={busy} onClick={() => run(() => arenaApi.flowControl("pause"))}>暂停流程</button>)}
        {flow?.status === "AWAITING_HOST" && <button className="button button-primary" disabled={busy} onClick={() => run(() => arenaApi.flowControl("advance"))}>裁决完成，下一步</button>}
        {active && <button className="button button-quiet" disabled={busy} onClick={() => run(() => arenaApi.flowControl("stop"))}>结束流程</button>}
      </div>
      <details><summary>编辑流程步骤</summary><label>步骤 JSON<textarea rows="6" value={flowText} onChange={event => setFlowText(event.target.value)} placeholder='[{"phase":"讨论","target_seats":[1,2],"action_type":"SPEAK","prompt":"请发言"}]' /></label><div className="director-actions"><button className="button button-quiet" onClick={() => setFlowText(JSON.stringify(flow?.steps || [], null, 2))}>读取当前步骤</button><button className="button button-primary" disabled={busy || active || !flowText.trim()} onClick={() => run(() => arenaApi.startFlow(JSON.parse(flowText)), "流程已启动")}>按步骤启动</button></div></details>
    </details>
    <details className="director-section"><summary>启动游戏</summary><label>游戏 Mod<select value={game} onChange={event => setGame(event.target.value)}><option value="">选择游戏</option>{games.map(id => <option key={id}>{id}</option>)}</select></label><div className="check-grid">{seats.map(seat => <label className="check-row" key={seat.seat_id}><input type="checkbox" checked={targets.includes(seat.seat_id)} onChange={() => setTargets(previous => previous.includes(seat.seat_id) ? previous.filter(id => id !== seat.seat_id) : [...previous, seat.seat_id])} />{seat.name}</label>)}</div><button className="button button-primary button-wide" disabled={busy || !game || !targets.length} onClick={() => run(() => arenaApi.startGame({ name: game, seats: targets, options: {} }), "游戏已启动")}>开始游戏</button>{["RUNNING", "PAUSED"].includes(snapshot?.game?.status) && <button className="button button-quiet button-wide" disabled={busy} onClick={() => run(() => arenaApi.gameControl("stop"))}>结束当前游戏</button>}</details>
    <details className="director-section"><summary>消息与席位接入</summary><label>接收席位<select value={recipient} onChange={event => { setRecipient(event.target.value); setBootstrap(""); setDirectory(snapshot?.workspace_paths?.[event.target.value] || ""); }}><option value="">全员</option>{seats.map(seat => <option key={seat.seat_id} value={seat.seat_id}>{seat.name}</option>)}</select></label><label>消息<textarea value={message} onChange={event => setMessage(event.target.value)} rows="3" /></label><button className="button button-quiet button-wide" disabled={busy || !message.trim()} onClick={() => run(async () => { await arenaApi.command({ command_type: recipient ? "SEND_PRIVATE" : "BROADCAST", target_seat: recipient ? Number(recipient) : null, content: message }); setMessage(""); }, "消息已发送")}>发送消息</button>
      {connectSeat && <><label>本机工作目录<input value={directory} onChange={event => setDirectory(event.target.value)} /></label><button className="button button-quiet button-wide" disabled={busy || !directory.trim()} onClick={() => run(() => arenaApi.workspace(connectSeat.seat_id, directory), "工作目录已登记")}>登记工作目录</button><button className="button button-quiet button-wide" onClick={makeBootstrap}>生成接入命令</button>{bootstrap && <label>在该席位工作目录执行<textarea readOnly rows="4" value={bootstrap} onFocus={event => event.target.select()} /></label>}</>}
    </details>
  </>;
}
