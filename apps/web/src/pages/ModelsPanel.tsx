import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  post,
  request,
  scopeQuery,
  type Binding,
  type ModeStatus,
  type ArtifactRecord,
  type ArtifactRegistration,
  type DeploymentRecord,
  type DeploymentInput,
  type DeploymentTest,
  type ActivateDeployment,
} from '../api';
import { Badge, Icon } from '../components/ui';

type Artifact = ArtifactRecord;
type Deployment = DeploymentRecord;
interface ActivationResult {
  status: ModeStatus;
  deployment_id: string;
  reenable_required: boolean;
}
const deploymentLabels: Record<string, string> = {
  unverified: '待测试',
  ready: '连接已验证',
  failed: '测试失败',
  revoked: '已失效',
};

export default function ModelsPanel({
  token,
  binding,
  status,
  onStatus,
  onError,
}: {
  token: string;
  binding: Binding;
  status: ModeStatus | null;
  onStatus: (status: ModeStatus) => void;
  onError: (error: unknown) => void;
}) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [artifactPath, setArtifactPath] = useState('');
  const [artifactId, setArtifactId] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [model, setModel] = useState('');
  const [keyEnv, setKeyEnv] = useState('CHATTWIN_MODEL_KEY');
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const query = scopeQuery(binding);
  const activeId =
    typeof status?.payload.model_deployment_id === 'string'
      ? status.payload.model_deployment_id
      : null;
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const results = await Promise.allSettled([
        request<Artifact[]>(token, `/model-artifacts${query}`, { signal }),
        request<Deployment[]>(token, `/model-deployments${query}`, { signal }),
      ]);
      if (signal?.aborted) return;
      if (results[0].status === 'fulfilled') setArtifacts(results[0].value);
      else onError(results[0].reason);
      if (results[1].status === 'fulfilled') setDeployments(results[1].value);
      else onError(results[1].reason);
    },
    [token, query, onError],
  );
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);
  async function registerArtifact(event: FormEvent) {
    event.preventDefault();
    setBusy('artifact');
    setNotice('');
    try {
      const result = await post<Artifact>(token, '/model-artifacts', {
        persona_id: binding.persona_id,
        relationship_id: binding.relationship_id,
        artifact_path: artifactPath.trim(),
      } satisfies ArtifactRegistration);
      await refresh();
      setArtifactId(result.id);
      setArtifactPath('');
      setNotice('产物校验通过，已登记到当前关系。仍需部署端点测试与明确启用。');
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function registerDeployment(event: FormEvent) {
    event.preventDefault();
    setBusy('deployment');
    setNotice('');
    try {
      await post(token, '/model-deployments', {
        persona_id: binding.persona_id,
        relationship_id: binding.relationship_id,
        artifact_id: artifactId || null,
        endpoint: endpoint.trim(),
        model: model.trim(),
        key_env: keyEnv.trim(),
        label: label.trim(),
      } satisfies DeploymentInput);
      await refresh();
      setNotice('部署配置已保存，尚未调用模型。请测试连接后再启用。');
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function test(deployment: Deployment) {
    setBusy(deployment.id);
    setNotice('');
    try {
      const result = await post<DeploymentTest>(
        token,
        `/model-deployments/${encodeURIComponent(deployment.id)}/test`,
        {},
      );
      await refresh();
      setNotice(
        `端点测试结果：${deploymentLabels[result.status] ?? result.status}。使用固定虚构提示；返回模型 ${result.probe.model}${result.probe.synthetic ? '（合成提供方）' : ''}。`,
      );
    } catch (error) {
      onError(error);
      await refresh();
    } finally {
      setBusy('');
    }
  }
  async function activate(deployment: Deployment) {
    if (!status) return;
    setBusy(deployment.id);
    setNotice('');
    try {
      const result = await post<ActivationResult>(
        token,
        `/model-deployments/${encodeURIComponent(deployment.id)}/activate`,
        {
          binding_id: binding.id,
          expected_control_epoch: status.control_epoch,
        } satisfies ActivateDeployment,
      );
      onStatus(result.status);
      await refresh();
      setNotice('模型版本已切换，旧候选已失效。AI 保持停止；请在试聊核对后主动开启。');
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function rollback() {
    if (!status) return;
    setBusy('rollback');
    setNotice('');
    try {
      const result = await post<ActivationResult>(token, '/model-deployments/rollback', {
        binding_id: binding.id,
        expected_control_epoch: status.control_epoch,
      } satisfies ActivateDeployment);
      onStatus(result.status);
      await refresh();
      setNotice('已回滚到上一可用版本。AI 保持停止，不会自动恢复回复。');
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  return (
    <>
      <div className="form-grid">
        <section className="panel form-panel">
          <div className="card-title">
            <Icon name="train" />
            <h2>登记已完成的 LoRA 产物</h2>
          </div>
          <p className="muted">
            选择私有目录中已经训练成功的产物。服务会核对
            manifest、权重和关系范围，不接受空目录或假训练结果。
          </p>
          <form onSubmit={registerArtifact}>
            <label htmlFor="artifact-path">
              本机产物目录
              <input
                id="artifact-path"
                value={artifactPath}
                required
                onChange={(event) => setArtifactPath(event.target.value)}
                placeholder="粘贴训练作业输出的私有目录绝对路径"
              />
            </label>
            <button className="button secondary" disabled={!!busy || !artifactPath.trim()}>
              校验并登记产物
            </button>
          </form>
          {artifacts.length > 0 && (
            <ul className="artifact-list">
              {artifacts.map((artifact) => (
                <li key={artifact.id}>
                  <Badge tone={artifact.status === 'validated' ? 'green' : 'amber'}>
                    {artifact.status === 'validated'
                      ? '已校验'
                      : artifact.status === 'revoked'
                        ? '已失效'
                        : artifact.status}
                  </Badge>
                  <strong>
                    {typeof artifact.manifest.base_model_id === 'string'
                      ? artifact.manifest.base_model_id
                      : '关系专用 adapter'}
                  </strong>
                  <code>{artifact.artifact_path}</code>
                  <small>{new Date(artifact.created_at).toLocaleString('zh-CN')}</small>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="panel form-panel">
          <div className="card-title">
            <Icon name="settings" />
            <h2>配置一个模型版本</h2>
          </div>
          <form onSubmit={registerDeployment}>
            <label>
              版本名称
              <input
                required
                maxLength={100}
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="例如：我的基础模型 / 小禾关系 LoRA v1"
              />
            </label>
            <label>
              关联 LoRA 产物
              <select value={artifactId} onChange={(event) => setArtifactId(event.target.value)}>
                <option value="">基础模型（不加载 adapter）</option>
                {artifacts.map((artifact) => (
                  <option
                    key={artifact.id}
                    value={artifact.id}
                    disabled={artifact.status !== 'validated'}
                  >
                    {artifact.id}
                    {artifact.status === 'revoked' ? ' · 已失效' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label>
              模型服务端点
              <input
                type="url"
                required
                value={endpoint}
                onChange={(event) => setEndpoint(event.target.value)}
                placeholder="http://127.0.0.1:9000/v1 或 HTTPS 模型服务"
              />
            </label>
            <div className="form-row">
              <label>
                模型名称
                <input
                  required
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="模型端点接受的 model 名称"
                />
              </label>
              <label>
                密钥环境变量名
                <input
                  required
                  pattern="CHATTWIN_MODEL_KEY(_[A-Z0-9_]+)?"
                  value={keyEnv}
                  onChange={(event) => setKeyEnv(event.target.value)}
                  spellCheck={false}
                />
              </label>
            </div>
            <p className="field-hint">
              这里只填写环境变量的名称，不填写密钥。保存配置不会调用模型；测试连接会发送一条固定虚构提示。
            </p>
            <button
              className="button primary"
              disabled={!!busy || !endpoint.trim() || !model.trim() || !label.trim()}
            >
              保存待验证版本
              <Icon name="plus" size={16} />
            </button>
          </form>
        </section>
      </div>
      {notice && (
        <p className="success-note spaced" role="status">
          {notice}
        </p>
      )}
      <section className="panel form-panel spaced-panel">
        <div className="panel-header plain">
          <h2>模型版本与回滚</h2>
          <button
            className="button secondary small-button"
            disabled={!!busy || !status}
            onClick={() => void rollback()}
          >
            回滚上一版本
          </button>
        </div>
        <p className="muted">登记 → 连接测试 → 明确启用。切换版本会停止当前 AI，并作废旧候选。</p>
        {deployments.length ? (
          <div className="deployment-list">
            {deployments.map((deployment) => (
              <article key={deployment.id}>
                <div className="job-heading">
                  <div>
                    <strong>{deployment.label || deployment.model}</strong>
                    <small>
                      {deployment.model} · {deployment.artifact_id ? '关系专用 LoRA' : '基础模型'}
                    </small>
                  </div>
                  <Badge
                    tone={
                      activeId === deployment.id
                        ? 'green'
                        : deployment.status === 'ready'
                          ? 'green'
                          : 'amber'
                    }
                  >
                    {activeId === deployment.id
                      ? '当前版本'
                      : (deploymentLabels[deployment.status] ?? deployment.status)}
                  </Badge>
                </div>
                <p className="endpoint-label">{deployment.endpoint}</p>
                <div className="action-row">
                  <button
                    className="button secondary small-button"
                    disabled={!!busy || deployment.status === 'revoked'}
                    onClick={() => void test(deployment)}
                  >
                    {busy === deployment.id ? '正在处理…' : '测试连接'}
                  </button>
                  <button
                    className="button primary small-button"
                    disabled={
                      !!busy ||
                      !status ||
                      deployment.status !== 'ready' ||
                      activeId === deployment.id
                    }
                    onClick={() => void activate(deployment)}
                  >
                    启用此版本
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-copy spaced">
            尚无配置的模型版本。网页演示仍可使用当前 MockProvider，不会被当作真实模型验收。
          </p>
        )}
      </section>
    </>
  );
}
