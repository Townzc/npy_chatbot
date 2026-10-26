import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import ImportPanel from './pages/ImportPanel';
import PersonalizationPage from './pages/PersonalizationPage';
import TrainingPanel from './pages/TrainingPanel';
import ModelsPanel from './pages/ModelsPanel';
import OperationsPanel from './pages/OperationsPanel';
import ReconciliationPanel from './pages/ReconciliationPanel';
import { Icon, Badge } from './components/ui';
import PageBoundary from './components/PageBoundary';
import {
  APIError,
  messageOf,
  post,
  request,
  scopeQuery,
  type Binding,
  type Memory,
  type ModeCommand,
  type ModeStatus,
  type NamedInput,
  type Persona,
  type Relationship,
  type RelationshipInput,
  type SandboxInput,
  type SandboxReply,
  type ScopeInput,
  type WorkspaceState,
  type DeploymentRecord,
  type SessionInput,
  type SessionResponse,
} from './api';

type Page = 'sandbox' | 'imports' | 'memories' | 'training' | 'models' | 'settings';
type Variant = SandboxInput['variant'];
type ChatLine = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  model?: string;
  synthetic?: boolean;
  variant?: Variant;
};
const SESSION_KEY = 'chattwin.session.v1';
const modeLabels: Record<string, string> = {
  HUMAN: '本人模式',
  ENABLING: '正在通知',
  AI_ACTIVE: 'AI 模式',
  PAUSED: '故障暂停',
};
const receiptLabels: Record<string, string> = {
  planned: '等待发送',
  submitting: '发送中',
  confirmed: '已确认',
  rejected: '发送失败',
  unknown: '待核对',
  cancelled: '已取消',
};

function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? 'brand-small' : ''}`}>
      <span className="brand-mark">
        <i />
        <i />
      </span>
      <span>
        ChatTwin<span className="brand-dot">.</span>
      </span>
    </div>
  );
}

function Login({
  onLogin,
  notice,
}: {
  onLogin: (token: string, state: WorkspaceState) => void;
  notice: string;
}) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    let issuedToken = '';
    try {
      const session = await post<SessionResponse>(token.trim(), '/auth/session', {
        lifetime_seconds: 3600,
      } satisfies SessionInput);
      issuedToken = session.token;
      setToken('');
      const state = await request<WorkspaceState>(session.token, '/state');
      onLogin(session.token, state);
    } catch (e) {
      setError(messageOf(e));
      if (issuedToken) {
        void request(issuedToken, '/auth/session', {
          method: 'DELETE',
          signal: AbortSignal.timeout(5000),
        }).catch(() => undefined);
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-layout">
      <section className="login-story">
        <Brand />
        <div className="login-copy">
          <span className="eyebrow">YOUR WORDS. YOUR WORLD.</span>
          <h1>
            有你的语气，
            <br />
            也有你的边界。
          </h1>
          <p>
            从聊天记录开始，建立自己的个人 AI。
            <br />
            每一段记忆，都有出处；每一次回复，都由你掌控。
          </p>
          <div className="orbit">
            <div className="orbit-ring" />
            <div className="orbit-ring inner" />
            <span className="orbit-person">你</span>
            <span className="orbit-twin">
              <Icon name="leaf" size={32} />
            </span>
            <span className="orbit-tag">一点点，更像你</span>
          </div>
        </div>
        <span className="login-foot">LOCAL FIRST · PRIVATE BY DESIGN</span>
      </section>
      <section className="login-form">
        <div>
          <Badge tone="green">本地工作台</Badge>
          <h2>欢迎回来</h2>
          <p className="muted">使用本机创建的访问凭证进入工作台。</p>
          {notice && (
            <p className="field-hint" role="status">
              {notice}
            </p>
          )}
          <form onSubmit={submit}>
            <label htmlFor="access-token">访问凭证</label>
            <input
              id="access-token"
              type="password"
              required
              autoComplete="current-password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="粘贴本机访问凭证"
            />
            <p className="field-hint">凭证由服务启动时创建，不是模型 API Key。</p>
            {error && (
              <div role="alert" className="error">
                {error}
              </div>
            )}
            <button className="button primary full" disabled={busy || !token.trim()}>
              {busy ? '正在连接…' : '进入工作台'}
              <Icon name="arrow" size={18} />
            </button>
          </form>
          <div className="login-note">
            <Icon name="lock" size={17} />
            <span>
              本人凭证仅用于换取短期会话。浏览器只保存短期令牌，默认一小时到期；服务重启后需重新登录。
            </span>
          </div>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(SESSION_KEY) ?? '');
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [page, setPage] = useState<Page>('sandbox');
  const [bindingId, setBindingId] = useState('');
  const [status, setStatus] = useState<ModeStatus | null>(null);
  const [error, setError] = useState('');
  const [authNotice, setAuthNotice] = useState('');
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [busy, setBusy] = useState('');
  const [creatingScope, setCreatingScope] = useState(false);
  const [modeBusy, setModeBusy] = useState({ enable: false, takeover: false });
  const modeCommands = useRef<Record<string, string>>({});
  const activeBinding = useRef('');
  const binding = state?.bindings.find((b) => b.id === bindingId) ?? null;
  const persona = state?.personas.find((p) => p.id === binding?.persona_id);
  const relationship = state?.relationships.find((r) => r.id === binding?.relationship_id);

  const clearSession = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY);
    setToken('');
    setState(null);
    setStatus(null);
    setBindingId('');
    setCreatingScope(false);
    setError('');
    modeCommands.current = {};
    activeBinding.current = '';
  }, []);
  const handleError = useCallback(
    (e: unknown) => {
      if (e instanceof APIError && e.status === 401) {
        setAuthNotice('会话已失效，请重新登录。登录状态不会改变 AI 的运行模式。');
        clearSession();
      } else setError(messageOf(e));
    },
    [clearSession],
  );
  async function logout() {
    if (logoutBusy || modeBusy.takeover) return;
    setLogoutBusy(true);
    try {
      await request(token, '/auth/session', {
        method: 'DELETE',
        signal: AbortSignal.timeout(5000),
      });
      setAuthNotice('短期会话已撤销。退出登录不会改变 AI 的运行模式。');
    } catch {
      setAuthNotice(
        '已清理此浏览器的登录状态，服务尚未确认会话撤销。退出登录不会改变 AI 的运行模式。',
      );
    } finally {
      clearSession();
      setLogoutBusy(false);
    }
  }
  const applyWorkspaceState = useCallback((next: WorkspaceState) => {
    setState(next);
    setBindingId((previous) =>
      next.bindings.some((b) => b.id === previous) ? previous : (next.bindings[0]?.id ?? ''),
    );
  }, []);
  const applyModeStatus = useCallback((next: ModeStatus) => {
    if (next.binding_id !== activeBinding.current) return;
    setStatus((previous) =>
      !previous ||
      next.control_epoch > previous.control_epoch ||
      (next.control_epoch === previous.control_epoch && next.context_seq >= previous.context_seq)
        ? next
        : previous,
    );
  }, []);
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    request<WorkspaceState>(token, '/state', { signal: controller.signal })
      .then(applyWorkspaceState)
      .catch((e) => {
        if (!controller.signal.aborted) handleError(e);
      });
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
        const next = await request<ModeStatus>(
          token,
          `/conversations/${encodeURIComponent(bindingId)}/status`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) applyModeStatus(next);
      } catch (e) {
        if (!controller.signal.aborted) handleError(e);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [bindingId, token, handleError, applyModeStatus]);

  async function loadDemo() {
    setBusy('demo');
    setError('');
    try {
      applyWorkspaceState(await post<WorkspaceState>(token, '/demo', {}));
    } catch (e) {
      handleError(e);
    } finally {
      setBusy('');
    }
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
    setModeBusy((previous) => ({ ...previous, [action]: true }));
    setError('');
    const commandKey = `${targetBinding}:${action}`;
    const commandId = modeCommands.current[commandKey] ?? crypto.randomUUID();
    modeCommands.current[commandKey] = commandId;
    try {
      const command: ModeCommand = {
        command_id: commandId,
        action,
        expected_control_epoch: status?.control_epoch ?? 0,
      };
      const result = await post<ModeStatus>(
        token,
        `/conversations/${encodeURIComponent(targetBinding)}/mode`,
        command,
      );
      applyModeStatus(result);
      delete modeCommands.current[commandKey];
    } catch (e) {
      handleError(e);
    } finally {
      setModeBusy((previous) => ({ ...previous, [action]: false }));
    }
  }
  const nav: { id: Page; icon: string; title: string; number: string }[] = [
    { id: 'sandbox', icon: 'chat', title: '网页试聊', number: '01' },
    { id: 'imports', icon: 'import', title: '导入与身份', number: '02' },
    { id: 'memories', icon: 'leaf', title: '风格与记忆', number: '03' },
    { id: 'training', icon: 'train', title: '数据集与训练', number: '04' },
    { id: 'models', icon: 'train', title: '模型版本', number: '05' },
    { id: 'settings', icon: 'settings', title: '运行与维护', number: '06' },
  ];
  if (!token)
    return (
      <Login
        notice={authNotice}
        onLogin={(nextToken, nextState) => {
          sessionStorage.setItem(SESSION_KEY, nextToken);
          setToken(nextToken);
          setAuthNotice('');
          applyWorkspaceState(nextState);
        }}
      />
    );
  if (!state)
    return (
      <main className="loading">
        <Brand />
        <p>正在连接本地工作台…</p>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        <button className="button subtle" disabled={logoutBusy} onClick={() => void logout()}>
          返回登录
        </button>
      </main>
    );

  return (
    <div className="workspace">
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">
          个人 AI 工作台 <span>LOCAL</span>
        </div>
        <nav aria-label="主导航">
          {nav.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              aria-label={item.title}
              title={item.title}
              aria-current={page === item.id ? 'page' : undefined}
              onClick={() => setPage(item.id)}
            >
              <Icon name={item.icon} />
              <span>{item.title}</span>
              <small>{item.number}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card">
            <Icon name="lock" size={19} />
            <strong>你的数据，由你保管</strong>
            <p>每个档案、每段关系都有独立边界。</p>
          </div>
          <button
            className="logout"
            aria-label="退出登录"
            disabled={logoutBusy || modeBusy.takeover}
            onClick={() => void logout()}
          >
            <span className="avatar small">我</span>
            <span>
              本机所有者<small>{logoutBusy ? '正在退出…' : '短期会话已认证'}</small>
            </span>
            <Icon name="logout" size={17} />
          </button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb">
            工作台 <span>/</span> <strong>{nav.find((n) => n.id === page)?.title}</strong>
          </div>
          <div className="topbar-right">
            <span className="version">v{state.version}</span>
            <Badge tone="green">本地控制台</Badge>
            <button
              className="mobile-logout"
              aria-label="退出登录"
              disabled={logoutBusy || modeBusy.takeover}
              onClick={() => void logout()}
            >
              <Icon name="logout" size={16} />
            </button>
          </div>
        </header>
        <main className="main-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">YOUR PERSONAL AI</span>
              <h1>
                {page === 'sandbox'
                  ? '让对话，慢慢有你的样子。'
                  : {
                      imports: '从自己的表达开始。',
                      memories: '记住重要的，也尊重边界。',
                      training: '让训练的每一步都有依据。',
                      models: '每一个模型版本，都可核对与回退。',
                      settings: '看得见的状态，握得住的控制。',
                    }[page]}
              </h1>
              <p>
                {page === 'sandbox'
                  ? '在这里试聊、比较和调整。准备好了，再由你决定下一步。'
                  : {
                      imports: '预览记录、确认本人身份，再选择这一段关系的数据用途。',
                      memories: '只检索当前档案与关系内、经你确认的记忆。',
                      training: '先冻结可追溯的数据集，再在独立环境中执行真实 LoRA。',
                      models: '登记产物、测试端点，再明确选择当前会话使用的模型。',
                      settings: '从本地演示到真实接入，每项能力分别验证。',
                    }[page]}
              </p>
            </div>
            <button
              className="button secondary"
              onClick={() => setCreatingScope((previous) => !previous)}
              aria-expanded={creatingScope}
            >
              <Icon name="plus" size={17} />
              新建档案 / 关系
            </button>
          </div>
          {error && (
            <div className="error dismissible" role="alert">
              <span>{error}</span>
              <button aria-label="关闭错误提示" onClick={() => setError('')}>
                ×
              </button>
            </div>
          )}
          {creatingScope && (
            <ScopeCreator
              token={token}
              personas={state.personas}
              onCreated={scopeCreated}
              onCancel={() => setCreatingScope(false)}
              onError={handleError}
            />
          )}
          {!state.bindings.length && page === 'settings' ? (
            <PageBoundary key="setup-operations">
              <SettingsPanel state={state} binding={null} status={null} />
              <OperationsPanel token={token} onError={handleError} />
            </PageBoundary>
          ) : !state.bindings.length ? (
            <section className="empty-onboarding">
              <div className="empty-graphic">
                <Icon name="leaf" size={44} />
              </div>
              <span className="eyebrow">A SMALL FIRST STEP</span>
              <h2>先用一段虚构对话，认识 ChatTwin</h2>
              <p>无需 QQ 账号或模型密钥，即可体验导入、关系记忆、通知与接管的本地闭环。</p>
              <button className="button primary" onClick={loadDemo} disabled={busy === 'demo'}>
                开始虚构数据演示 <Icon name="arrow" size={18} />
              </button>
              <small>示例中的人物与聊天内容均为虚构。</small>
            </section>
          ) : (
            <>
              <section className="scope-bar" aria-label="当前作用域">
                <div className="avatar">{persona?.name?.slice(0, 1) ?? '我'}</div>
                <div className="scope-persona">
                  <span>当前个人档案</span>
                  <strong>{persona?.name ?? '未命名档案'}</strong>
                </div>
                <span className="scope-divider" />
                <label className="scope-select">
                  <span>当前关系与会话</span>
                  <select
                    aria-label="选择当前关系与会话"
                    value={bindingId}
                    onChange={(e) => setBindingId(e.target.value)}
                  >
                    {state.bindings.map((b) => (
                      <option key={b.id} value={b.id}>
                        {state.relationships.find((r) => r.id === b.relationship_id)?.name ??
                          b.recipient_id}{' '}
                        ·{' '}
                        {b.channel === 'onebot'
                          ? 'QQ'
                          : b.channel === 'fake'
                            ? '虚构演示'
                            : '网页试聊'}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="scope-kind">
                  <Icon name="lock" size={15} /> 关系内隔离
                </div>
              </section>
              <PageBoundary key={`${page}:${bindingId}`}>
                {page === 'sandbox' && binding && (
                  <Sandbox
                    key={binding.id}
                    token={token}
                    binding={binding}
                    relationshipName={relationship?.name ?? '当前关系'}
                    status={status}
                    setStatus={applyModeStatus}
                    provider={state.provider}
                    onError={handleError}
                  />
                )}
                {page === 'imports' && binding && (
                  <ImportPanel
                    key={binding.id}
                    token={token}
                    binding={binding}
                    onError={handleError}
                  />
                )}
                {page === 'memories' && binding && (
                  <PersonalizationPage
                    key={binding.id}
                    token={token}
                    binding={binding}
                    onError={handleError}
                  />
                )}
                {page === 'training' && binding && (
                  <TrainingPanel
                    key={binding.id}
                    token={token}
                    binding={binding}
                    state={state}
                    onError={handleError}
                  />
                )}
                {page === 'models' && binding && (
                  <ModelsPanel
                    key={binding.id}
                    token={token}
                    binding={binding}
                    status={status}
                    onStatus={applyModeStatus}
                    onError={handleError}
                  />
                )}
                {page === 'settings' && (
                  <>
                    <SettingsPanel state={state} binding={binding} status={status} />
                    {binding && (
                      <ReconciliationPanel
                        token={token}
                        binding={binding}
                        status={status}
                        onStatus={applyModeStatus}
                        onError={handleError}
                      />
                    )}
                    <OperationsPanel
                      token={token}
                      personaId={binding?.persona_id}
                      onError={handleError}
                    />
                  </>
                )}
              </PageBoundary>
            </>
          )}
          <footer className="page-footer">
            <span>ChatTwin · 从真实表达中成长</span>
            <span>默认无外发遥测</span>
          </footer>
        </main>
        {binding && (
          <div className="control-bar">
            <div className="control-state">
              <span className={`control-dot ${status?.mode === 'AI_ACTIVE' ? 'active' : ''}`} />
              <div>
                <strong>{status ? modeLabels[status.mode] : '正在读取状态…'}</strong>
                <span>
                  {status?.mode === 'AI_ACTIVE'
                    ? '开启通知已确认，可以回复新消息'
                    : status?.mode === 'ENABLING'
                      ? '通知确认后才允许 AI 回复'
                      : status?.mode === 'PAUSED'
                        ? 'AI 已暂停，请检查通知与异常'
                        : 'AI 已停止，等待你主动开启'}
                </span>
              </div>
            </div>
            <div className="control-actions">
              <button
                className="button secondary"
                disabled={
                  modeBusy.enable ||
                  modeBusy.takeover ||
                  !status ||
                  status.mode === 'AI_ACTIVE' ||
                  status.mode === 'ENABLING'
                }
                onClick={() => void changeMode('enable')}
              >
                开启 AI
              </button>
              <button
                className="button takeover"
                disabled={modeBusy.takeover}
                onClick={() => void changeMode('takeover')}
              >
                <Icon name="stop" size={16} />
                本人接管
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ScopeCreator({
  token,
  personas,
  onCreated,
  onCancel,
  onError,
}: {
  token: string;
  personas: Persona[];
  onCreated: (binding: Binding) => Promise<void>;
  onCancel: () => void;
  onError: (e: unknown) => void;
}) {
  const [personaId, setPersonaId] = useState('new');
  const [personaName, setPersonaName] = useState('');
  const [relationshipName, setRelationshipName] = useState('');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('');
  const steps = useRef<{ persona?: Persona; relationship?: Relationship; binding?: Binding }>({});
  const partial = Boolean(steps.current.persona || steps.current.relationship);
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      if (!steps.current.persona) {
        setProgress('正在创建个人档案…');
        if (personaId === 'new') {
          const body: NamedInput = { name: personaName.trim() };
          steps.current.persona = await post<Persona>(token, '/personas', body);
        } else steps.current.persona = personas.find((item) => item.id === personaId);
      }
      if (!steps.current.persona) throw new Error('所选档案不存在，请重新选择。');
      if (!steps.current.relationship) {
        setProgress('正在建立独立关系空间…');
        const body: RelationshipInput = {
          persona_id: steps.current.persona.id,
          name: relationshipName.trim(),
        };
        steps.current.relationship = await post<Relationship>(token, '/relationships', body);
      }
      if (!steps.current.binding) {
        setProgress('正在创建网页试聊会话…');
        const body: ScopeInput = {
          persona_id: steps.current.persona.id,
          relationship_id: steps.current.relationship.id,
        };
        steps.current.binding = await post<Binding>(token, '/bindings', body);
      }
      setProgress('正在打开新的关系空间…');
      await onCreated(steps.current.binding);
    } catch (e) {
      setProgress(
        partial || steps.current.persona
          ? '已完成的步骤已保留，重试将继续创建。'
          : '创建尚未完成。',
      );
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel scope-creator" aria-labelledby="scope-create-title">
      <div className="scope-create-heading">
        <div>
          <span className="eyebrow">A SPACE OF YOUR OWN</span>
          <h2 id="scope-create-title">创建自己的档案与关系空间</h2>
        </div>
        <button className="text-button" disabled={busy} onClick={onCancel}>
          收起
        </button>
      </div>
      <p className="muted">每段关系使用独立的记忆、数据集和网页会话。新会话默认处于本人模式。</p>
      <form onSubmit={create}>
        <div className="scope-create-fields">
          <label>
            个人档案
            <select
              value={personaId}
              disabled={busy || partial}
              onChange={(e) => setPersonaId(e.target.value)}
            >
              <option value="new">创建新档案</option>
              {personas.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          {personaId === 'new' && (
            <label>
              新档案名称
              <input
                required
                maxLength={100}
                value={personaName}
                disabled={busy || partial}
                onChange={(e) => setPersonaName(e.target.value)}
                placeholder="例如：我的 AI"
              />
            </label>
          )}
          <label>
            新关系名称
            <input
              required
              maxLength={100}
              value={relationshipName}
              disabled={busy || partial}
              onChange={(e) => setRelationshipName(e.target.value)}
              placeholder="例如：和阿林的对话"
            />
          </label>
        </div>
        <div className="scope-create-bottom">
          <p role="status">{progress || '创建后，你可以导入这段关系的聊天记录并确认本人身份。'}</p>
          <button
            className="button primary"
            disabled={
              busy || (!personaName.trim() && personaId === 'new') || !relationshipName.trim()
            }
          >
            {busy ? '正在创建…' : partial ? '继续创建' : '创建并开始导入'}
            <Icon name="arrow" size={16} />
          </button>
        </div>
      </form>
    </section>
  );
}

function Sandbox({
  token,
  binding,
  relationshipName,
  status,
  setStatus,
  provider,
  onError,
}: {
  token: string;
  binding: Binding;
  relationshipName: string;
  status: ModeStatus | null;
  setStatus: (value: ModeStatus) => void;
  provider: WorkspaceState['provider'];
  onError: (e: unknown) => void;
}) {
  const [variant, setVariant] = useState<Variant>('B2');
  const [text, setText] = useState('');
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [busy, setBusy] = useState(false);
  const [usedMemories, setUsedMemories] = useState<Memory[]>([]);
  const [deployment, setDeployment] = useState<DeploymentRecord | null>(null);
  const deploymentId =
    typeof status?.payload.model_deployment_id === 'string'
      ? status.payload.model_deployment_id
      : 'mock-v1';
  const usingDeployment = deploymentId !== 'mock-v1';
  const usesSelectedDeployment = usingDeployment && (!deployment?.artifact_id || variant === 'B3');
  const modelName = usesSelectedDeployment
    ? (deployment?.model ?? '读取所选模型版本…')
    : provider.name;
  useEffect(() => {
    setDeployment(null);
    if (!usingDeployment) return;
    const aborter = new AbortController();
    request<DeploymentRecord[]>(token, `/model-deployments${scopeQuery(binding)}`, {
      signal: aborter.signal,
    })
      .then((items) => {
        if (!aborter.signal.aborted)
          setDeployment(items.find((item) => item.id === deploymentId) ?? null);
      })
      .catch((error) => {
        if (!aborter.signal.aborted) onError(error);
      });
    return () => aborter.abort();
  }, [token, binding, deploymentId, usingDeployment, onError]);
  const bottom = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [lines.length]);
  useEffect(() => {
    if (status && status.mode !== 'AI_ACTIVE') controller.current?.abort();
  }, [status?.mode]);
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy || (variant === 'B3' && !deployment?.artifact_id)) return;
    const input = text.trim();
    setText('');
    setBusy(true);
    setLines((previous) => [...previous, { id: crypto.randomUUID(), role: 'user', text: input }]);
    const aborter = new AbortController();
    controller.current = aborter;
    try {
      const body: SandboxInput = { binding_id: binding.id, text: input, variant };
      const result = await request<SandboxReply>(token, '/sandbox/messages', {
        method: 'POST',
        body: JSON.stringify(body),
        signal: aborter.signal,
      });
      if (mounted.current) {
        setLines((previous) => [
          ...previous,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            text: result.text,
            model: result.model,
            synthetic: result.synthetic,
            variant,
          },
        ]);
        setStatus(result.status);
        setUsedMemories(result.memories);
      }
    } catch (e) {
      if (!aborter.signal.aborted) onError(e);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <div className="sandbox-grid">
      <section className="panel chat-panel">
        <div className="panel-header">
          <div>
            <Icon name="chat" />
            <h2>试聊空间</h2>
          </div>
          <Badge tone={binding.channel === 'onebot' ? 'amber' : 'neutral'}>
            {binding.channel === 'onebot'
              ? '已绑定 QQ · 检查接入状态'
              : binding.channel === 'fake'
                ? '虚构数据演示'
                : '本地网页试聊'}
          </Badge>
        </div>
        <div className="variant-tabs" role="group" aria-label="对照模式">
          {(
            [
              { id: 'B0', title: '基础模型', detail: '原始表达' },
              { id: 'B1', title: '风格增强', detail: '加入表达习惯' },
              { id: 'B2', title: '记忆增强', detail: '加入关系记忆' },
              { id: 'B3', title: 'LoRA 对照', detail: '微调 + 风格记忆' },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              className={variant === item.id ? 'selected' : ''}
              aria-pressed={variant === item.id}
              onClick={() => setVariant(item.id)}
              disabled={busy || (item.id === 'B3' && !deployment?.artifact_id)}
              title={
                item.id === 'B3' && !deployment?.artifact_id
                  ? '需先启用当前关系的已验证 LoRA 部署'
                  : item.detail
              }
            >
              <span>{item.id}</span>
              <strong>{item.title}</strong>
              <small>{item.detail}</small>
            </button>
          ))}
        </div>
        <div className="chat-scroll" aria-live="polite" aria-busy={busy}>
          {lines.length === 0 ? (
            <div className="chat-welcome">
              <div className="twin-symbol">
                <span />
                <span />
              </div>
              <h3>从一句熟悉的问候开始</h3>
              <p>用 {relationshipName} 的口吻，试着发来一条消息。</p>
              <div className="suggestions">
                {['周末想去看展吗？', '今天有点累，想聊聊天。', '还记得我喜欢什么吗？'].map(
                  (prompt) => (
                    <button key={prompt} onClick={() => setText(prompt)}>
                      {prompt}
                      <Icon name="arrow" size={14} />
                    </button>
                  ),
                )}
              </div>
            </div>
          ) : (
            lines.map((line) => (
              <div key={line.id} className={`chat-line ${line.role}`}>
                <span className={`avatar ${line.role === 'assistant' ? 'twin' : ''}`}>
                  {line.role === 'assistant' ? <Icon name="leaf" size={17} /> : '你'}
                </span>
                <div>
                  <small>
                    {line.role === 'assistant'
                      ? `${line.synthetic ? '演示回复' : 'AI 回复'} · ${line.variant ?? ''} · ${line.model}`
                      : '试聊输入'}
                  </small>
                  <div className="bubble">{line.text}</div>
                </div>
              </div>
            ))
          )}
          {busy && (
            <div className="thinking">
              <span />
              <span />
              <span />
              <small>正在生成，随时可接管</small>
            </div>
          )}
          <div ref={bottom} />
        </div>
        <form className="composer" onSubmit={send}>
          <label className="sr-only" htmlFor="chat-input">
            试聊消息
          </label>
          <textarea
            id="chat-input"
            rows={2}
            maxLength={4000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (text.trim() && !busy && status?.mode === 'AI_ACTIVE')
                  e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={
              status?.mode === 'AI_ACTIVE'
                ? '写一句话，看看个人 AI 会怎样回应…'
                : '先点击底部「开启 AI」，通知确认后开始试聊'
            }
          />
          <div className="composer-bottom">
            <span>
              {usesSelectedDeployment
                ? '所选上下文将发送到配置的模型端点'
                : provider.remote
                  ? '所选上下文将发送到远端模型'
                  : 'Enter 发送 · Shift + Enter 换行'}
            </span>
            <button
              type="submit"
              className="send-button"
              aria-label="发送试聊消息"
              disabled={
                busy ||
                !text.trim() ||
                status?.mode !== 'AI_ACTIVE' ||
                (variant === 'B3' && !deployment?.artifact_id)
              }
            >
              <Icon name="arrow" size={20} />
            </button>
          </div>
        </form>
      </section>
      <aside className="context-column">
        <section className="panel context-card">
          <span className="eyebrow">IN THIS CONVERSATION</span>
          <h3>这一段关系的上下文</h3>
          <div className="context-person">
            <span className="avatar soft">{relationshipName.slice(0, 1)}</span>
            <div>
              <strong>{relationshipName}</strong>
              <small>独立关系空间</small>
            </div>
          </div>
          <div className="context-fact">
            <span>当前模型</span>
            <strong>{modelName}</strong>
          </div>
          <div className="context-fact">
            <span>增强方式</span>
            <strong>
              {variant === 'B0'
                ? '仅基础模型'
                : variant === 'B1'
                  ? '风格示例'
                  : variant === 'B3'
                    ? 'LoRA + 风格记忆'
                    : '风格 + 关系记忆'}
            </strong>
          </div>
          <div className="context-fact">
            <span>回复来源</span>
            <strong>
              {usesSelectedDeployment
                ? deployment?.artifact_id
                  ? '关系专用 LoRA'
                  : '配置的模型端点'
                : provider.name.toLowerCase().includes('mock')
                  ? '合成演示'
                  : provider.remote
                    ? '远端模型'
                    : '本地模型'}
            </strong>
          </div>
          <p className="fine-print">风格与记忆增强不会改变模型权重。</p>
        </section>
        <section className="panel context-card">
          <div className="card-title">
            <Icon name="leaf" size={18} />
            <h3>本轮使用的记忆</h3>
          </div>
          {usedMemories.length ? (
            usedMemories.map((memory) => (
              <p className="memory-used" key={memory.id}>
                {memory.text ?? memory.payload?.text}
              </p>
            ))
          ) : (
            <p className="empty-copy">发送消息后，这里会显示本轮实际检索到的记忆。</p>
          )}
        </section>
        <NotificationPanel status={status} />
        <div className="quiet-note">
          <Icon name="lock" size={16} />
          <p>
            {binding.channel === 'onebot'
              ? '真实 QQ 接入与网页试聊分开验证。'
              : '此空间使用本地演示通道，不代表真实 QQ 已通过验证。'}
          </p>
        </div>
      </aside>
    </div>
  );
}

function NotificationPanel({ status }: { status: ModeStatus | null }) {
  return (
    <section className="panel context-card">
      <div className="card-title">
        <Icon name="check" size={18} />
        <h3>模式通知</h3>
      </div>
      <ol className="notification-list">
        {status?.notifications.length ? (
          status.notifications.slice(-4).map((item) => (
            <li key={item.id}>
              <span className={`timeline-dot ${item.status === 'confirmed' ? 'confirmed' : ''}`} />
              <strong>{item.text}</strong>
              <small>{receiptLabels[item.status] ?? item.status}</small>
            </li>
          ))
        ) : (
          <li className="empty-copy">开启 AI 后，先确认通知，再开始回复。</li>
        )}
      </ol>
      {!!status?.in_flight.length && (
        <p className="warning">有 {status.in_flight.length} 条请求已开始传输，接管后仍可能到达。</p>
      )}
    </section>
  );
}

function SettingsPanel({
  state,
  binding,
  status,
}: {
  state: WorkspaceState;
  binding: Binding | null;
  status: ModeStatus | null;
}) {
  return (
    <div className="form-grid">
      <section className="panel form-panel">
        <h2>当前运行环境</h2>
        <dl className="settings-list">
          <div>
            <dt>核心版本</dt>
            <dd>{state.version}</dd>
          </div>
          <div>
            <dt>默认推理提供方</dt>
            <dd>{state.provider.name}</dd>
          </div>
          <div>
            <dt>数据流向</dt>
            <dd>
              {status?.payload.model_deployment_id &&
              status.payload.model_deployment_id !== 'mock-v1'
                ? '当前使用关系内配置的模型端点；详见模型版本页'
                : state.provider.remote
                  ? '选定上下文发送到远端模型'
                  : '当前使用本地模型或演示提供方'}
            </dd>
          </div>
          <div>
            <dt>当前通道</dt>
            <dd>
              {!binding
                ? '尚未创建会话'
                : binding.channel === 'onebot'
                  ? 'OneBot · 实机状态另行验证'
                  : binding.channel === 'fake'
                    ? '本地虚构演示'
                    : '本地网页试聊'}
            </dd>
          </div>
          <div>
            <dt>训练环境</dt>
            <dd>在数据集与训练页查看实际 Python / CUDA 检测和作业状态</dd>
          </div>
          <div>
            <dt>控制版本</dt>
            <dd>{status?.control_epoch ?? '—'}</dd>
          </div>
        </dl>
        <div className="notice">
          <Icon name="lock" size={18} />
          <p>
            QQ
            账号、模型密钥与本人访问凭证分别配置。当前网页不接受通过聊天消息修改收件人或模型配置。
          </p>
        </div>
      </section>
      <div>
        <NotificationPanel status={status} />
        <section className="panel form-panel mt">
          <h2>能力与证据分开记录</h2>
          <p className="muted">
            本地协议测试、真实 QQ
            原会话、模型训练与手机离网接管分别验收。页面显示的合成演示结果，不代表这些实机条件已通过。
          </p>
        </section>
      </div>
    </div>
  );
}
