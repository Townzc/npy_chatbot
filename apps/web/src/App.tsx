import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { APIError, messageOf, post, request, type Binding, type Memory, type MemoryInput, type ModeCommand, type ModeStatus, type NamedInput, type Persona, type Relationship, type RelationshipInput, type SandboxInput, type SandboxReply, type ScopeInput, type WorkspaceState } from './api';

type Page = 'sandbox' | 'imports' | 'memories' | 'training' | 'settings';
type Variant = 'B0' | 'B1' | 'B2';
type ChatLine = { id: string; role: 'user' | 'assistant'; text: string; model?: string; synthetic?: boolean };
const SESSION_KEY = 'chattwin.auth.v1';
const modeLabels: Record<string, string> = { HUMAN: '本人模式', ENABLING: '正在通知', AI_ACTIVE: 'AI 模式', PAUSED: '故障暂停' };
const receiptLabels: Record<string, string> = { planned: '等待发送', submitting: '发送中', confirmed: '已确认', rejected: '发送失败', unknown: '待核对', cancelled: '已取消' };

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    chat: <><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2v-9.5A8.5 8.5 0 0 1 10.5 4H13a8 8 0 0 1 8 7.5Z" /><path d="M7 10h9M7 14h6" /></>,
    import: <><path d="M12 3v12m-4-4 4 4 4-4M5 15v5h14v-5" /></>,
    leaf: <><path d="M20 3c-8-1-15 2-15 8a6 6 0 0 0 10 4c3-3 4-8 5-12Z" /><path d="M4 21c1-5 4-9 9-12" /></>,
    train: <><rect x="6" y="6" width="12" height="12" rx="3" /><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4" /><path d="M10 10h4v4h-4z" /></>,
    settings: <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" /><circle cx="15" cy="17" r="3" /></>,
    arrow: <><path d="m5 12 14 0m-5-5 5 5-5 5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    check: <path d="m5 12 4 4L19 6" />,
    lock: <><rect x="5" y="10" width="14" height="11" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></>,
    refresh: <><path d="M20 7V3l-4 1M4 17v4l4-1M20 7a9 9 0 0 0-15-2M4 17a9 9 0 0 0 15 2" /></>,
    stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
    logout: <><path d="M10 3H4v18h6M10 12h11m-4-4 4 4-4 4" /></>,
    file: <><path d="M14 2H5v20h14V7l-5-5v5h5M8 12h8M8 16h6" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.chat}</svg>;
}

function Brand({ small = false }: { small?: boolean }) {
  return <div className={`brand ${small ? 'brand-small' : ''}`}><span className="brand-mark"><i /><i /></span><span>ChatTwin<span className="brand-dot">.</span></span></div>;
}

function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'green' | 'amber' | 'neutral' }) {
  return <span className={`badge badge-${tone}`}><span className="status-dot" />{children}</span>;
}

function Report({ value }: { value: unknown }) {
  const [showDetail, setShowDetail] = useState(false);
  const result = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const fields = [['total', '消息总数'], ['inserted', '新增记录'], ['duplicates', '重复记录'], ['bad_rows', '错误行'], ['valid_text', '有效文本'], ['candidate_training_targets', '可训练目标']] as const;
  const counts = result.counts && typeof result.counts === 'object' ? result.counts as Record<string, unknown> : {};
  const splitFields = [['train', '训练样本'], ['validation', '验证样本'], ['test', '测试样本']] as const;
  const preview = Array.isArray(result.preview) ? result.preview.slice(0, 4) as Record<string, unknown>[] : [];
  const senders = Array.isArray(result.senders) ? result.senders as { id: string; name: string }[] : [];
  const errors = Array.isArray(result.errors) ? result.errors.slice(0, 3) as { record_index?: number; error?: string }[] : [];
  const formatDate = (date: unknown) => typeof date === 'string' && !Number.isNaN(Date.parse(date)) ? new Date(date).toLocaleString('zh-CN') : '未提供';
  return <section className="result-report" aria-label="处理结果">
    <div className="result-report-heading"><strong>{typeof result.inserted === 'number' ? '导入结果' : typeof result.total === 'number' ? '记录预览' : '数据集结果'}</strong>{typeof result.identity_confirmed === 'boolean' && <Badge tone={result.identity_confirmed ? 'green' : 'amber'}>{result.identity_confirmed ? '本人身份已确认' : '本人身份待选择'}</Badge>}</div>
    <dl className="result-metrics">{fields.map(([key, label]) => typeof result[key] === 'number' ? <div key={key}><dt>{label}</dt><dd>{result[key].toLocaleString('zh-CN')}</dd></div> : null)}{splitFields.map(([key, label]) => typeof counts[key] === 'number' ? <div key={key}><dt>{label}</dt><dd>{counts[key].toLocaleString('zh-CN')}</dd></div> : null)}</dl>
    {(result.start || result.end) ? <p className="result-date">记录时间：{formatDate(result.start)} — {formatDate(result.end)}</p> : null}
    {typeof result.human_origin_confirmed === 'boolean' && <p className="result-note">{result.human_origin_confirmed ? '已确认选定的本人记录为真人发言。' : '未确认真人来源；未知来源不会成为训练标签。'}</p>}
    {preview.length > 0 && <div className="result-preview"><span>内容抽样 · 前 {preview.length} 条</span>{preview.map((message, index) => {
      const content = message.content && typeof message.content === 'object' ? message.content as Record<string, unknown> : {};
      const senderId = typeof message.sender_id === 'string' ? message.sender_id : '未知发送者';
      const text = typeof content.text === 'string' && content.text ? content.text : '[非文字内容]';
      return <article key={typeof message.id === 'string' ? message.id : index}><small>{senders.find(sender => sender.id === senderId)?.name || senderId}<time>{formatDate(message.occurred_at)}</time></small><p>{text.length > 160 ? `${text.slice(0, 160)}…` : text}</p></article>;
    })}</div>}
    {errors.length > 0 && <div className="result-errors" role="status"><strong>需要处理的错误</strong>{errors.map((error, index) => <p key={index}>第 {error.record_index ?? '?'} 行：{error.error ?? '无法解析该记录'}</p>)}{typeof result.bad_rows === 'number' && result.bad_rows > errors.length && <small>其余错误可在详细报告中查看。</small>}</div>}
    <details className="report" onToggle={event => setShowDetail(event.currentTarget.open)}><summary>查看详细报告（JSON）</summary>{showDetail && <pre>{JSON.stringify(value, null, 2)}</pre>}</details>
  </section>;
}

function Login({ onLogin }: { onLogin: (token: string, state: WorkspaceState) => void }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const state = await request<WorkspaceState>(token.trim(), '/state'); onLogin(token.trim(), state); }
    catch (e) { setError(messageOf(e)); }
    finally { setBusy(false); }
  }
  return <main className="login-layout">
    <section className="login-story"><Brand /><div className="login-copy"><span className="eyebrow">YOUR WORDS. YOUR WORLD.</span><h1>有你的语气，<br />也有你的边界。</h1><p>从聊天记录开始，建立自己的个人 AI。<br />每一段记忆，都有出处；每一次回复，都由你掌控。</p><div className="orbit"><div className="orbit-ring" /><div className="orbit-ring inner" /><span className="orbit-person">你</span><span className="orbit-twin"><Icon name="leaf" size={32} /></span><span className="orbit-tag">一点点，更像你</span></div></div><span className="login-foot">LOCAL FIRST · PRIVATE BY DESIGN</span></section>
    <section className="login-form"><div><Badge tone="green">本地工作台</Badge><h2>欢迎回来</h2><p className="muted">使用本机创建的访问凭证进入工作台。</p><form onSubmit={submit}><label htmlFor="access-token">访问凭证</label><input id="access-token" type="password" required autoComplete="current-password" value={token} onChange={e => setToken(e.target.value)} placeholder="粘贴本机访问凭证" /><p className="field-hint">凭证由服务启动时创建，不是模型 API Key。</p>{error && <div role="alert" className="error">{error}</div>}<button className="button primary full" disabled={busy || !token.trim()}>{busy ? '正在连接…' : '进入工作台'}<Icon name="arrow" size={18} /></button></form><div className="login-note"><Icon name="lock" size={17} /><span>凭证只保存在当前浏览器会话，不会出现在链接中。</span></div></div></section>
  </main>;
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(SESSION_KEY) ?? '');
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [page, setPage] = useState<Page>('sandbox');
  const [bindingId, setBindingId] = useState('');
  const [status, setStatus] = useState<ModeStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [creatingScope, setCreatingScope] = useState(false);
  const [modeBusy, setModeBusy] = useState({ enable: false, takeover: false });
  const modeCommands = useRef<Record<string, string>>({});
  const activeBinding = useRef('');
  const binding = state?.bindings.find(b => b.id === bindingId) ?? null;
  const persona = state?.personas.find(p => p.id === binding?.persona_id);
  const relationship = state?.relationships.find(r => r.id === binding?.relationship_id);

  const logout = useCallback(() => { sessionStorage.removeItem(SESSION_KEY); setToken(''); setState(null); setStatus(null); setBindingId(''); }, []);
  const handleError = useCallback((e: unknown) => { if (e instanceof APIError && e.status === 401) logout(); else setError(messageOf(e)); }, [logout]);
  const applyWorkspaceState = useCallback((next: WorkspaceState) => {
    setState(next);
    setBindingId(previous => next.bindings.some(b => b.id === previous) ? previous : next.bindings[0]?.id ?? '');
  }, []);
  const applyModeStatus = useCallback((next: ModeStatus) => {
    if (next.binding_id !== activeBinding.current) return;
    setStatus(previous => !previous || next.control_epoch > previous.control_epoch ||
      (next.control_epoch === previous.control_epoch && next.context_seq >= previous.context_seq)
      ? next : previous);
  }, []);
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    request<WorkspaceState>(token, '/state', { signal: controller.signal }).then(applyWorkspaceState).catch(e => { if (!controller.signal.aborted) handleError(e); });
    return () => controller.abort();
  }, [token, applyWorkspaceState, handleError]);

  useEffect(() => {
    activeBinding.current = bindingId;
    setStatus(null);
    if (!bindingId || !token) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await request<ModeStatus>(token, `/conversations/${encodeURIComponent(bindingId)}/status`, { signal: controller.signal });
        if (!controller.signal.aborted) applyModeStatus(next);
      } catch (e) { if (!controller.signal.aborted) handleError(e); }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [bindingId, token, handleError, applyModeStatus]);

  async function loadDemo() {
    setBusy('demo'); setError('');
    try { applyWorkspaceState(await post<WorkspaceState>(token, '/demo', {})); }
    catch (e) { handleError(e); }
    finally { setBusy(''); }
  }
  async function scopeCreated(nextBinding: Binding) {
    const next = await request<WorkspaceState>(token, '/state');
    applyWorkspaceState(next);
    setBindingId(nextBinding.id);
    setCreatingScope(false);
    setPage('imports');
  }
  async function changeMode(action: 'enable' | 'takeover') {
    if (!bindingId) return;
    const targetBinding = bindingId;
    setModeBusy(previous => ({ ...previous, [action]: true })); setError('');
    const commandKey = `${targetBinding}:${action}`;
    const commandId = modeCommands.current[commandKey] ?? crypto.randomUUID();
    modeCommands.current[commandKey] = commandId;
    try {
      const command: ModeCommand = { command_id: commandId, action, expected_control_epoch: status?.control_epoch ?? 0 };
      const result = await post<ModeStatus>(token, `/conversations/${encodeURIComponent(targetBinding)}/mode`, command);
      applyModeStatus(result);
      delete modeCommands.current[commandKey];
    } catch (e) { handleError(e); }
    finally { setModeBusy(previous => ({ ...previous, [action]: false })); }
  }
  const nav: { id: Page; icon: string; title: string; number: string }[] = [
    { id: 'sandbox', icon: 'chat', title: '网页试聊', number: '01' },
    { id: 'imports', icon: 'import', title: '导入与身份', number: '02' },
    { id: 'memories', icon: 'leaf', title: '关系记忆', number: '03' },
    { id: 'training', icon: 'train', title: '数据集与训练', number: '04' },
    { id: 'settings', icon: 'settings', title: '运行状态', number: '05' },
  ];
  if (!token) return <Login onLogin={(nextToken, nextState) => { sessionStorage.setItem(SESSION_KEY, nextToken); setToken(nextToken); applyWorkspaceState(nextState); }} />;
  if (!state) return <main className="loading"><Brand /><p>正在连接本地工作台…</p>{error && <div role="alert" className="error">{error}</div>}<button className="button subtle" onClick={logout}>返回登录</button></main>;

  return <div className="workspace">
    <aside className="sidebar"><Brand /><div className="workspace-label">个人 AI 工作台 <span>LOCAL</span></div><nav aria-label="主导航">{nav.map(item => <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} aria-label={item.title} title={item.title} aria-current={page === item.id ? 'page' : undefined} onClick={() => setPage(item.id)}><Icon name={item.icon} /><span>{item.title}</span><small>{item.number}</small></button>)}</nav><div className="sidebar-bottom"><div className="privacy-card"><Icon name="lock" size={19} /><strong>你的数据，由你保管</strong><p>每个档案、每段关系都有独立边界。</p></div><button className="logout" onClick={logout}><span className="avatar small">我</span><span>本机所有者<small>已认证</small></span><Icon name="logout" size={17} /></button></div></aside>
    <div className="workspace-main">
      <header className="topbar"><div className="breadcrumb">工作台 <span>/</span> <strong>{nav.find(n => n.id === page)?.title}</strong></div><div className="topbar-right"><span className="version">v{state.version}</span><Badge tone={state.provider.remote ? 'amber' : 'green'}>{state.provider.remote ? '使用远端模型' : '本地运行'}</Badge><button className="mobile-logout" aria-label="退出登录" onClick={logout}><Icon name="logout" size={16} /></button></div></header>
      <main className="main-content">
        <div className="page-heading"><div><span className="eyebrow">YOUR PERSONAL AI</span><h1>{page === 'sandbox' ? '让对话，慢慢有你的样子。' : { imports: '从自己的表达开始。', memories: '记住重要的，也尊重边界。', training: '让训练的每一步都有依据。', settings: '看得见的状态，握得住的控制。' }[page]}</h1><p>{page === 'sandbox' ? '在这里试聊、比较和调整。准备好了，再由你决定下一步。' : { imports: '预览记录、确认本人身份，再选择这一段关系的数据用途。', memories: '只检索当前档案与关系内、经你确认的记忆。', training: '先冻结可追溯的数据集，再在独立环境中执行真实 LoRA。', settings: '从本地演示到真实接入，每项能力分别验证。' }[page]}</p></div><button className="button secondary" onClick={() => setCreatingScope(previous => !previous)} aria-expanded={creatingScope}><Icon name="plus" size={17} />新建档案 / 关系</button></div>
        {error && <div className="error dismissible" role="alert"><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}>×</button></div>}
        {creatingScope && <ScopeCreator token={token} personas={state.personas} onCreated={scopeCreated} onCancel={() => setCreatingScope(false)} onError={handleError} />}
        {!state.bindings.length ? <section className="empty-onboarding"><div className="empty-graphic"><Icon name="leaf" size={44} /></div><span className="eyebrow">A SMALL FIRST STEP</span><h2>先用一段虚构对话，认识 ChatTwin</h2><p>无需 QQ 账号或模型密钥，即可体验导入、关系记忆、通知与接管的本地闭环。</p><button className="button primary" onClick={loadDemo} disabled={busy === 'demo'}>开始虚构数据演示 <Icon name="arrow" size={18} /></button><small>示例中的人物与聊天内容均为虚构。</small></section> : <>
          <section className="scope-bar" aria-label="当前作用域"><div className="avatar">{persona?.name?.slice(0, 1) ?? '我'}</div><div className="scope-persona"><span>当前个人档案</span><strong>{persona?.name ?? '未命名档案'}</strong></div><span className="scope-divider" /><label className="scope-select"><span>当前关系与会话</span><select aria-label="选择当前关系与会话" value={bindingId} onChange={e => setBindingId(e.target.value)}>{state.bindings.map(b => <option key={b.id} value={b.id}>{state.relationships.find(r => r.id === b.relationship_id)?.name ?? b.recipient_id} · {b.channel === 'onebot' ? 'QQ' : b.channel === 'fake' ? '虚构演示' : '网页试聊'}</option>)}</select></label><div className="scope-kind"><Icon name="lock" size={15} /> 关系内隔离</div></section>
          {page === 'sandbox' && binding && <Sandbox key={binding.id} token={token} binding={binding} relationshipName={relationship?.name ?? '当前关系'} status={status} setStatus={applyModeStatus} provider={state.provider} onError={handleError} />}
          {page === 'imports' && binding && <ImportPanel key={binding.id} token={token} binding={binding} onError={handleError} />}
          {page === 'memories' && binding && <MemoryPanel key={binding.id} token={token} binding={binding} onError={handleError} />}
          {page === 'training' && binding && <TrainingPanel key={binding.id} token={token} binding={binding} state={state} onError={handleError} />}
          {page === 'settings' && <SettingsPanel state={state} binding={binding} status={status} />}
        </>}
        <footer className="page-footer"><span>ChatTwin · 从真实表达中成长</span><span>默认无外发遥测</span></footer>
      </main>
      {binding && <div className="control-bar"><div className="control-state"><span className={`control-dot ${status?.mode === 'AI_ACTIVE' ? 'active' : ''}`} /><div><strong>{status ? modeLabels[status.mode] : '正在读取状态…'}</strong><span>{status?.mode === 'AI_ACTIVE' ? '开启通知已确认，可以回复新消息' : status?.mode === 'ENABLING' ? '通知确认后才允许 AI 回复' : status?.mode === 'PAUSED' ? 'AI 已暂停，请检查通知与异常' : 'AI 已停止，等待你主动开启'}</span></div></div><div className="control-actions"><button className="button secondary" disabled={modeBusy.enable || modeBusy.takeover || !status || status.mode === 'AI_ACTIVE' || status.mode === 'ENABLING'} onClick={() => void changeMode('enable')}>开启 AI</button><button className="button takeover" disabled={modeBusy.takeover} onClick={() => void changeMode('takeover')}><Icon name="stop" size={16} />本人接管</button></div></div>}
    </div>
  </div>;
}

function ScopeCreator({ token, personas, onCreated, onCancel, onError }: { token: string; personas: Persona[]; onCreated: (binding: Binding) => Promise<void>; onCancel: () => void; onError: (e: unknown) => void }) {
  const [personaId, setPersonaId] = useState('new');
  const [personaName, setPersonaName] = useState('');
  const [relationshipName, setRelationshipName] = useState('');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('');
  const steps = useRef<{ persona?: Persona; relationship?: Relationship; binding?: Binding }>({});
  const partial = Boolean(steps.current.persona || steps.current.relationship);
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    try {
      if (!steps.current.persona) {
        setProgress('正在创建个人档案…');
        if (personaId === 'new') {
          const body: NamedInput = { name: personaName.trim() };
          steps.current.persona = await post<Persona>(token, '/personas', body);
        } else steps.current.persona = personas.find(item => item.id === personaId);
      }
      if (!steps.current.persona) throw new Error('所选档案不存在，请重新选择。');
      if (!steps.current.relationship) {
        setProgress('正在建立独立关系空间…');
        const body: RelationshipInput = { persona_id: steps.current.persona.id, name: relationshipName.trim() };
        steps.current.relationship = await post<Relationship>(token, '/relationships', body);
      }
      if (!steps.current.binding) {
        setProgress('正在创建网页试聊会话…');
        const body: ScopeInput = { persona_id: steps.current.persona.id, relationship_id: steps.current.relationship.id };
        steps.current.binding = await post<Binding>(token, '/bindings', body);
      }
      setProgress('正在打开新的关系空间…');
      await onCreated(steps.current.binding);
    } catch (e) { setProgress(partial || steps.current.persona ? '已完成的步骤已保留，重试将继续创建。' : '创建尚未完成。'); onError(e); }
    finally { setBusy(false); }
  }
  return <section className="panel scope-creator" aria-labelledby="scope-create-title">
    <div className="scope-create-heading"><div><span className="eyebrow">A SPACE OF YOUR OWN</span><h2 id="scope-create-title">创建自己的档案与关系空间</h2></div><button className="text-button" disabled={busy} onClick={onCancel}>收起</button></div>
    <p className="muted">每段关系使用独立的记忆、数据集和网页会话。新会话默认处于本人模式。</p>
    <form onSubmit={create}>
      <div className="scope-create-fields">
        <label>个人档案<select value={personaId} disabled={busy || partial} onChange={e => setPersonaId(e.target.value)}><option value="new">创建新档案</option>{personas.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {personaId === 'new' && <label>新档案名称<input required maxLength={100} value={personaName} disabled={busy || partial} onChange={e => setPersonaName(e.target.value)} placeholder="例如：我的 AI" /></label>}
        <label>新关系名称<input required maxLength={100} value={relationshipName} disabled={busy || partial} onChange={e => setRelationshipName(e.target.value)} placeholder="例如：和阿林的对话" /></label>
      </div>
      <div className="scope-create-bottom"><p role="status">{progress || '创建后，你可以导入这段关系的聊天记录并确认本人身份。'}</p><button className="button primary" disabled={busy || (!personaName.trim() && personaId === 'new') || !relationshipName.trim()}>{busy ? '正在创建…' : partial ? '继续创建' : '创建并开始导入'}<Icon name="arrow" size={16} /></button></div>
    </form>
  </section>;
}

function Sandbox({ token, binding, relationshipName, status, setStatus, provider, onError }: { token: string; binding: Binding; relationshipName: string; status: ModeStatus | null; setStatus: (value: ModeStatus) => void; provider: WorkspaceState['provider']; onError: (e: unknown) => void }) {
  const [variant, setVariant] = useState<Variant>('B2');
  const [text, setText] = useState('');
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [busy, setBusy] = useState(false);
  const [usedMemories, setUsedMemories] = useState<Memory[]>([]);
  const bottom = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort(); }; }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [lines.length]);
  useEffect(() => { if (status && status.mode !== 'AI_ACTIVE') controller.current?.abort(); }, [status?.mode]);
  async function send(event: FormEvent) {
    event.preventDefault(); if (!text.trim() || busy) return;
    const input = text.trim(); setText(''); setBusy(true);
    setLines(previous => [...previous, { id: crypto.randomUUID(), role: 'user', text: input }]);
    const aborter = new AbortController(); controller.current = aborter;
    try {
      const body: SandboxInput = { binding_id: binding.id, text: input, variant };
      const result = await request<SandboxReply>(token, '/sandbox/messages', { method: 'POST', body: JSON.stringify(body), signal: aborter.signal });
      if (mounted.current) { setLines(previous => [...previous, { id: crypto.randomUUID(), role: 'assistant', text: result.text, model: result.model, synthetic: result.synthetic }]); setStatus(result.status); setUsedMemories(result.memories); }
    } catch (e) { if (!aborter.signal.aborted) onError(e); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <div className="sandbox-grid">
    <section className="panel chat-panel"><div className="panel-header"><div><Icon name="chat" /><h2>试聊空间</h2></div><Badge tone={binding.channel === 'onebot' ? 'amber' : 'neutral'}>{binding.channel === 'onebot' ? '已绑定 QQ · 检查接入状态' : binding.channel === 'fake' ? '虚构数据演示' : '本地网页试聊'}</Badge></div><div className="variant-tabs" role="group" aria-label="对照模式">{([{ id: 'B0', title: '基础模型', detail: '原始表达' }, { id: 'B1', title: '风格增强', detail: '加入表达习惯' }, { id: 'B2', title: '记忆增强', detail: '加入关系记忆' }] as const).map(item => <button key={item.id} className={variant === item.id ? 'selected' : ''} aria-pressed={variant === item.id} onClick={() => setVariant(item.id)} disabled={busy}><span>{item.id}</span><strong>{item.title}</strong><small>{item.detail}</small></button>)}</div>
      <div className="chat-scroll" aria-live="polite" aria-busy={busy}>{lines.length === 0 ? <div className="chat-welcome"><div className="twin-symbol"><span /><span /></div><h3>从一句熟悉的问候开始</h3><p>用 {relationshipName} 的口吻，试着发来一条消息。</p><div className="suggestions">{['周末想去看展吗？', '今天有点累，想聊聊天。', '还记得我喜欢什么吗？'].map(prompt => <button key={prompt} onClick={() => setText(prompt)}>{prompt}<Icon name="arrow" size={14} /></button>)}</div></div> : lines.map(line => <div key={line.id} className={`chat-line ${line.role}`}><span className={`avatar ${line.role === 'assistant' ? 'twin' : ''}`}>{line.role === 'assistant' ? <Icon name="leaf" size={17} /> : '你'}</span><div><small>{line.role === 'assistant' ? `${line.synthetic ? '演示回复' : 'AI 回复'} · ${line.model}` : '试聊输入'}</small><div className="bubble">{line.text}</div></div></div>)}{busy && <div className="thinking"><span /><span /><span /><small>正在生成，随时可接管</small></div>}<div ref={bottom} /></div>
      <form className="composer" onSubmit={send}><label className="sr-only" htmlFor="chat-input">试聊消息</label><textarea id="chat-input" rows={2} maxLength={4000} value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (text.trim() && !busy && status?.mode === 'AI_ACTIVE') e.currentTarget.form?.requestSubmit(); } }} placeholder={status?.mode === 'AI_ACTIVE' ? '写一句话，看看个人 AI 会怎样回应…' : '先点击底部「开启 AI」，通知确认后开始试聊'} /><div className="composer-bottom"><span>{provider.remote ? '所选上下文将发送到远端模型' : 'Enter 发送 · Shift + Enter 换行'}</span><button type="submit" className="send-button" aria-label="发送试聊消息" disabled={busy || !text.trim() || status?.mode !== 'AI_ACTIVE'}><Icon name="arrow" size={20} /></button></div></form>
    </section>
    <aside className="context-column"><section className="panel context-card"><span className="eyebrow">IN THIS CONVERSATION</span><h3>这一段关系的上下文</h3><div className="context-person"><span className="avatar soft">{relationshipName.slice(0, 1)}</span><div><strong>{relationshipName}</strong><small>独立关系空间</small></div></div><div className="context-fact"><span>当前模型</span><strong>{provider.name}</strong></div><div className="context-fact"><span>增强方式</span><strong>{variant === 'B0' ? '仅基础模型' : variant === 'B1' ? '风格示例' : '风格 + 关系记忆'}</strong></div><div className="context-fact"><span>回复来源</span><strong>{provider.name.toLowerCase().includes('mock') ? '合成演示' : provider.remote ? '远端模型' : '本地模型'}</strong></div><p className="fine-print">风格与记忆增强不会改变模型权重。</p></section>
      <section className="panel context-card"><div className="card-title"><Icon name="leaf" size={18} /><h3>本轮使用的记忆</h3></div>{usedMemories.length ? usedMemories.map(memory => <p className="memory-used" key={memory.id}>{memory.text ?? memory.payload?.text}</p>) : <p className="empty-copy">发送消息后，这里会显示本轮实际检索到的记忆。</p>}</section>
      <NotificationPanel status={status} />
      <div className="quiet-note"><Icon name="lock" size={16} /><p>{binding.channel === 'onebot' ? '真实 QQ 接入与网页试聊分开验证。' : '此空间使用本地演示通道，不代表真实 QQ 已通过验证。'}</p></div>
    </aside>
  </div>;
}

function NotificationPanel({ status }: { status: ModeStatus | null }) {
  return <section className="panel context-card"><div className="card-title"><Icon name="check" size={18} /><h3>模式通知</h3></div><ol className="notification-list">{status?.notifications.length ? status.notifications.slice(-4).map(item => <li key={item.id}><span className={`timeline-dot ${item.status === 'confirmed' ? 'confirmed' : ''}`} /><strong>{item.text}</strong><small>{receiptLabels[item.status] ?? item.status}</small></li>) : <li className="empty-copy">开启 AI 后，先确认通知，再开始回复。</li>}</ol>{!!status?.in_flight.length && <p className="warning">有 {status.in_flight.length} 条请求已开始传输，接管后仍可能到达。</p>}</section>;
}

function ImportPanel({ token, binding, onError }: { token: string; binding: Binding; onError: (e: unknown) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState('chatlab');
  const [account, setAccount] = useState('');
  const [owner, setOwner] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [mapping, setMapping] = useState('{}');
  const [preview, setPreview] = useState<unknown>(null);
  const [report, setReport] = useState<unknown>(null);
  const [busy, setBusy] = useState('');
  async function run(importNow: boolean) {
    if (!file) return;
    setBusy(importNow ? 'import' : 'inspect');
    const form = new FormData(); form.set('file', file); form.set('format', format); form.set('source_account_id', account.trim()); form.set('mapping', mapping);
    if (importNow) { form.set('persona_id', binding.persona_id); form.set('relationship_id', binding.relationship_id); form.set('owner_sender_id', owner.trim()); form.set('confirmed_human', String(confirmed)); }
    try { JSON.parse(mapping); const result = await request<unknown>(token, importNow ? '/imports' : '/imports/inspect', { method: 'POST', body: form }); if (importNow) setReport(result); else { setPreview(result); setOwner(''); setConfirmed(false); } }
    catch (e) { onError(e); }
    finally { setBusy(''); }
  }
  const senders = preview && typeof preview === 'object' && 'senders' in preview && Array.isArray(preview.senders) ? preview.senders as { id: string; name: string; source_account_id: string }[] : [];
  return <div className="form-grid"><section className="panel form-panel"><div className="section-number">01 <span>选择已导出的记录</span></div><p className="muted">支持文件格式与实际兼容性以预览报告为准。</p><label className="upload-box"><Icon name="import" size={30} /><strong>{file ? file.name : '选择聊天记录文件'}</strong><span>JSON、JSONL 或 CSV · 不自动读取设备数据库</span><input type="file" accept=".json,.jsonl,.csv" onChange={e => { setFile(e.target.files?.[0] ?? null); setPreview(null); setReport(null); }} /></label><div className="form-row"><label>导入格式<select value={format} onChange={e => { setFormat(e.target.value); setPreview(null); }}><option value="chatlab">ChatLab JSON / JSONL</option><option value="csv_mapping">通用 CSV</option><option value="canonical_jsonl">ChatTwin 规范 JSONL</option></select></label><label>来源账号稳定 ID<input value={account} onChange={e => { setAccount(e.target.value); setPreview(null); }} placeholder="例如 demo_source_account" /></label></div><details className="mapping-options"><summary>自定义字段与时区（可选）</summary><label>映射配置 JSON<textarea rows={5} value={mapping} onChange={e => { setMapping(e.target.value); setPreview(null); }} spellCheck={false} /></label><p className="field-hint">默认 CSV 列：sender_id、occurred_at、text、conversation。可设置 fields、timezone、time_unit 和 platform。规范 JSONL 缺少会话类型时，请仅在确认是私聊后添加 conversation_kind: "private"；群聊填写 "group"。</p></details><button className="button secondary" disabled={!file || !account.trim() || !!busy} onClick={() => void run(false)}><Icon name="file" size={17} />{busy === 'inspect' ? '正在解析…' : '预览文件与发送者'}</button>{preview != null && <Report value={preview} />}</section><section className="panel form-panel"><div className="section-number">02 <span>确认本人身份与用途</span></div><p className="muted">导出者不一定是训练目标。请从预览中的稳定 ID 明确选择本人。</p><label>本人的原始 sender_id{senders.length ? <select value={owner} onChange={e => { setOwner(e.target.value); setConfirmed(false); }}><option value="">请选择本人身份，不按昵称自动判断</option>{senders.map(sender => <option key={`${sender.source_account_id}:${sender.id}`} value={sender.id}>{sender.name || sender.id} · {sender.id}</option>)}</select> : <input value={owner} onChange={e => setOwner(e.target.value)} placeholder="从预览中复制稳定发送者 ID" />}</label><div className="scope-preview"><Icon name="lock" size={18} /><span>数据将进入当前选择的个人档案与关系空间。</span></div><label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /><span>我确认本次选定的本人记录由真人发出，允许用于风格与训练目标。<small>不确定时保持未勾选，记录仍可导入，但 unknown 不成为训练标签。</small></span></label><button className="button primary" disabled={!preview || !owner.trim() || !!busy} onClick={() => void run(true)}>{busy === 'import' ? '正在导入…' : '确认身份并导入'}<Icon name="arrow" size={17} /></button>{report != null && <Report value={report} />}<div className="quiet-note"><Icon name="file" size={16} /><p>导入成功仅表示提供的文件已解析，不能证明历史完整。训练数据集仍需单独构建与检查。</p></div></section></div>;
}

type SourceMessage = { id: string; sender_id: string; occurred_at: string; origin: string; content: { type: string; text: string | null } };

function MemoryPanel({ token, binding, onError }: { token: string; binding: Binding; onError: (e: unknown) => void }) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [messages, setMessages] = useState<SourceMessage[]>([]);
  const [text, setText] = useState('');
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [sourceFilter, setSourceFilter] = useState('');
  const [loadingSources, setLoadingSources] = useState(true);
  const [busy, setBusy] = useState(false);
  const query = `?persona_id=${encodeURIComponent(binding.persona_id)}&relationship_id=${encodeURIComponent(binding.relationship_id)}`;
  const refresh = useCallback(async () => { setMemories(await request<Memory[]>(token, `/memories${query}`)); }, [token, query]);
  useEffect(() => {
    const controller = new AbortController();
    const fetchMemories = request<Memory[]>(token, `/memories${query}`, { signal: controller.signal });
    const fetchSources = request<SourceMessage[]>(token, `/messages${query}`, { signal: controller.signal });
    void Promise.allSettled([fetchMemories, fetchSources]).then(([memoryResult, messageResult]) => {
      if (controller.signal.aborted) return;
      if (memoryResult.status === 'fulfilled') setMemories(memoryResult.value); else onError(memoryResult.reason);
      if (messageResult.status === 'fulfilled') setMessages(messageResult.value.filter(message => message.content.type === 'text' && !['ai', 'mode_notice', 'platform_system'].includes(message.origin)));
      else onError(messageResult.reason);
      setLoadingSources(false);
    });
    return () => controller.abort();
  }, [token, query, onError]);
  async function save(event: FormEvent) {
    event.preventDefault(); if (!sourceIds.length || !text.trim()) return; setBusy(true);
    try {
      const body: MemoryInput = { persona_id: binding.persona_id, relationship_id: binding.relationship_id, text: text.trim(), source_message_ids: sourceIds, confirmed: true };
      await post(token, '/memories', body); setText(''); setSourceIds([]); await refresh();
    } catch (e) { onError(e); } finally { setBusy(false); }
  }
  async function remove(id: string) { setBusy(true); try { await request(token, `/memories/${encodeURIComponent(id)}`, { method: 'DELETE' }); await refresh(); } catch (e) { onError(e); } finally { setBusy(false); } }
  const filteredSources = messages.filter(message => `${message.sender_id} ${message.content.text ?? ''}`.toLocaleLowerCase().includes(sourceFilter.toLocaleLowerCase()));
  return <div className="form-grid">
    <section className="panel form-panel"><div className="panel-header plain"><h2>已保存的关系记忆</h2><span className="count">{memories.length}</span></div>
      {memories.length ? <div className="memory-list">{memories.map(memory => <article key={memory.id}><Icon name="leaf" size={20} /><div><p>{memory.text ?? memory.payload?.text}</p><small>{memory.confirmed ?? memory.payload?.confirmed ? '已确认' : '候选 · 未用于检索'} · {(memory.source_message_ids ?? memory.payload?.source_message_ids ?? []).length} 条来源</small><details><summary>查看来源</summary>{(memory.source_message_ids ?? memory.payload?.source_message_ids ?? []).map(id => { const source = messages.find(message => message.id === id); return <p key={id} className="source-ids">{source ? `${source.sender_id}：${source.content.text}` : id}</p>; })}</details></div><button className="text-button" disabled={busy} onClick={() => void remove(memory.id)}>删除</button></article>)}</div> : <div className="empty-state"><Icon name="leaf" size={32} /><h3>给重要的事留个位置</h3><p>从当前关系的聊天记录中选择出处，再确认值得保存的记忆。</p></div>}
    </section>
    <section className="panel form-panel"><div className="section-number">+ <span>确认一条记忆</span></div>
      <form onSubmit={save}>
        <label htmlFor="memory-text">记忆内容</label><textarea id="memory-text" rows={4} required maxLength={2000} value={text} onChange={e => setText(e.target.value)} placeholder="例如：这位朋友更喜欢安静、不拥挤的展览。" />
        <fieldset className="source-fieldset"><legend>选择来源消息 <span>已选 {sourceIds.length} 条</span></legend>
          {loadingSources ? <p className="field-hint" role="status">正在载入当前关系的消息…</p> : messages.length ? <>
            <label htmlFor="source-filter" className="sr-only">筛选来源消息</label><input id="source-filter" type="search" value={sourceFilter} onChange={e => setSourceFilter(e.target.value)} placeholder="搜索已加载的消息内容或发送者" />
            <div className="source-options">{filteredSources.map(message => <label key={message.id} className="source-option"><input type="checkbox" checked={sourceIds.includes(message.id)} onChange={e => setSourceIds(previous => e.target.checked ? [...previous, message.id] : previous.filter(id => id !== message.id))} /><span><small>{message.sender_id} · {new Date(message.occurred_at).toLocaleString('zh-CN')}</small><span>{message.content.text}</span></span></label>)}{filteredSources.length === 0 && <p className="field-hint">已加载的消息中没有匹配内容。</p>}</div>
            <p className="field-hint">当前已加载 {messages.length} 条可用文字消息（服务端最多返回 200 条）。AI、通知和媒体不会作为事实来源。</p>
          </> : <div className="source-empty"><Icon name="file" size={20} /><p>当前关系还没有可用的来源消息。请先在「导入与身份」导入聊天记录。</p></div>}
        </fieldset>
        <p className="field-hint">保存表示你已核对内容与出处，这条记忆仅在当前关系中使用。</p><button className="button primary" disabled={busy || !text.trim() || !sourceIds.length}>确认并保存<Icon name="check" size={17} /></button>
      </form><p className="fine-print">删除记忆不等于已训练的模型权重自动遗忘。相关模型产物需另行停用或重新训练。</p>
    </section>
  </div>;
}

function TrainingPanel({ token, binding, state, onError }: { token: string; binding: Binding; state: WorkspaceState; onError: (e: unknown) => void }) {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<unknown>(null);
  async function build() { setBusy(true); try { setReport(await post(token, '/datasets', { persona_id: binding.persona_id, relationship_id: binding.relationship_id })); } catch (e) { onError(e); } finally { setBusy(false); } }
  return <><div className="training-steps"><div><span>01</span><strong>确认本人记录</strong><small>只选择已确认的人类发言</small></div><div><span>02</span><strong>冻结数据集</strong><small>完整片段划分后再构造样本</small></div><div><span>03</span><strong>真实 LoRA 训练</strong><small>独立环境执行并保存参数</small></div><div><span>04</span><strong>重载与对照验证</strong><small>评测通过后再决定启用</small></div></div><div className="form-grid"><section className="panel form-panel"><div className="card-title"><Icon name="file" /><h2>构建关系专用数据集</h2></div><p className="muted">根据当前档案的身份确认与数据用途生成快照。训练、验证、测试集独立划分，并保留来源与哈希。</p><ul className="check-list"><li><Icon name="check" size={16} />对方发言仅作为上下文</li><li><Icon name="check" size={16} />AI 回复、模式通知与未知来源不成为标签</li><li><Icon name="check" size={16} />不把相邻重叠窗口分到不同集合</li></ul><button className="button primary" onClick={() => void build()} disabled={busy}>{busy ? '正在构建…' : '构建数据集并查看报告'}<Icon name="arrow" size={17} /></button>{report != null && <Report value={report} />}</section><section className="panel form-panel training-status"><Badge tone={state.training.available ? 'green' : 'amber'}>{state.training.available ? '训练后端可用' : '训练环境待验证'}</Badge><h2>真实训练，独立验收</h2><p>{state.training.detail}</p><div className="training-requirements"><strong>完成训练必须具备</strong><p>实际参数更新 → 保存 adapter → 新进程加载 → 基础模型与微调模型对照。</p></div><p className="fine-print">数据集构建成功不代表训练完成；tiny smoke 也不代表参考底座的 GPU 训练通过。训练不会自动启动或上传数据。</p></section></div></>;
}

function SettingsPanel({ state, binding, status }: { state: WorkspaceState; binding: Binding | null; status: ModeStatus | null }) {
  return <div className="form-grid"><section className="panel form-panel"><h2>当前运行环境</h2><dl className="settings-list"><div><dt>核心版本</dt><dd>{state.version}</dd></div><div><dt>推理提供方</dt><dd>{state.provider.name}</dd></div><div><dt>数据流向</dt><dd>{state.provider.remote ? '选定上下文发送到远端模型' : '当前使用本地模型或演示提供方'}</dd></div><div><dt>当前通道</dt><dd>{binding?.channel === 'onebot' ? 'OneBot · 实机状态另行验证' : '本地虚构演示'}</dd></div><div><dt>训练状态</dt><dd>{state.training.available ? '后端可用，产物需独立验收' : '外部环境待验证'}</dd></div><div><dt>控制版本</dt><dd>{status?.control_epoch ?? '—'}</dd></div></dl><div className="notice"><Icon name="lock" size={18} /><p>QQ 账号、模型密钥与本人访问凭证分别配置。当前网页不接受通过聊天消息修改收件人或模型配置。</p></div></section><div><NotificationPanel status={status} /><section className="panel form-panel mt"><h2>能力与证据分开记录</h2><p className="muted">本地协议测试、真实 QQ 原会话、模型训练与手机离网接管分别验收。页面显示的合成演示结果，不代表这些实机条件已通过。</p></section></div></div>;
}
