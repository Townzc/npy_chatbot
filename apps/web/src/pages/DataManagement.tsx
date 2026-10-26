import { useCallback, useEffect, useState } from 'react';
import { request, scopeQuery, type Binding, type DeleteInput } from '../api';
import { Badge, Icon } from '../components/ui';

interface IdentityState {
  target_identity_id: string;
  identity_mapping_version: number;
  links: { id: string; source_account_id: string; sender_id: string }[];
  participants: {
    source_account_id: string;
    sender_id: string;
    name: string;
    message_count: number;
    roles: string[];
  }[];
}
interface ImportBatch {
  id: string;
  filename?: string;
  format: string;
  total: number;
  inserted?: number;
  duplicates?: number;
  owner_sender_id?: string;
  deleted?: boolean;
  status?: string;
}
interface DeletionImpact {
  impact_hash: string;
  batch_id: string;
  counts: Record<string, number>;
  affected_scopes?: unknown[];
  warnings: string[];
  revoked_dataset_ids?: string[];
  revoked_artifact_ids?: string[];
  revoked_deployment_ids?: string[];
}
const countLabels: Record<string, string> = {
  raw_messages_removed: '删除原始消息',
  raw_messages_retained_by_other_imports: '因其他批次引用而保留',
  message_uses_removed: '删除用途映射',
  jobs: '受影响作业',
  messages: '原始消息',
  message_uses: '档案用途映射',
  memories: '记忆',
  styles: '风格版本',
  datasets: '数据集',
  artifacts: '模型产物',
  deployments: '部署版本',
  raw_messages: '原始消息',
  uses: '用途映射',
};

export default function DataManagement({
  token,
  binding,
  revision,
  onError,
}: {
  token: string;
  binding: Binding;
  revision: number;
  onError: (error: unknown) => void;
}) {
  const [identities, setIdentities] = useState<IdentityState | null>(null);
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [impact, setImpact] = useState<DeletionImpact | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const query = scopeQuery(binding);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const results = await Promise.allSettled([
        request<IdentityState>(
          token,
          `/identities?persona_id=${encodeURIComponent(binding.persona_id)}`,
          { signal },
        ),
        request<ImportBatch[]>(token, `/imports${query}`, { signal }),
      ]);
      if (signal?.aborted) return;
      if (results[0].status === 'fulfilled') setIdentities(results[0].value);
      else onError(results[0].reason);
      if (results[1].status === 'fulfilled') setBatches(results[1].value);
      else onError(results[1].reason);
    },
    [token, binding.persona_id, query, onError],
  );
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh, revision]);
  async function previewDeletion(id: string) {
    setBusy(id);
    setReviewed(false);
    setNotice('');
    try {
      setImpact(
        await request<DeletionImpact>(
          token,
          `/imports/${encodeURIComponent(id)}/deletion-impact${query}`,
        ),
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function deleteBatch() {
    if (!impact || !reviewed) return;
    setBusy(impact.batch_id);
    try {
      await request(token, `/imports/${encodeURIComponent(impact.batch_id)}${query}`, {
        method: 'DELETE',
        body: JSON.stringify({ impact_hash: impact.impact_hash } satisfies DeleteInput),
      });
      setImpact(null);
      setReviewed(false);
      setNotice('本地删除已执行。相关模型已按影响记录失效；已有权重和备份的内容不会自动遗忘。');
      await refresh();
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  return (
    <div className="data-management">
      <section className="panel form-panel">
        <div className="panel-header plain">
          <h2>身份映射</h2>
          <Badge>版本 {identities?.identity_mapping_version ?? '—'}</Badge>
        </div>
        <p className="muted">
          人物以来源账号和原始发送者 ID 区分，昵称只用于展示。以下映射只属于当前个人档案。
        </p>
        {identities?.participants.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>人物</th>
                  <th>来源账号 / 发送者</th>
                  <th>用途身份</th>
                  <th>记录数</th>
                </tr>
              </thead>
              <tbody>
                {identities.participants.map((participant) => (
                  <tr key={`${participant.source_account_id}:${participant.sender_id}`}>
                    <td>{participant.name || '未命名'}</td>
                    <td>
                      <code>{participant.source_account_id}</code>
                      <small>{participant.sender_id}</small>
                    </td>
                    <td>
                      {participant.roles
                        .map(
                          (role) =>
                            ({ owner: '本人', partner: '对方', other: '其他', system: '系统' })[
                              role
                            ] ?? role,
                        )
                        .join('、')}
                    </td>
                    <td>{participant.message_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-copy spaced">导入并确认身份后，这里会展示稳定映射。</p>
        )}
        {identities?.links.length ? (
          <p className="field-hint">
            已确认 {identities.links.length} 条本人来源映射。目标身份：
            {identities.target_identity_id}
          </p>
        ) : null}
      </section>
      <section className="panel form-panel">
        <div className="panel-header plain">
          <h2>导入批次与删除影响</h2>
          <span className="count">{batches.length}</span>
        </div>
        {batches.length ? (
          <ul className="batch-list">
            {batches.map((batch) => (
              <li key={batch.id}>
                <div>
                  <strong>{batch.filename || batch.format}</strong>
                  <small>
                    {batch.total} 条记录 · 新增 {batch.inserted ?? '—'} · 重复{' '}
                    {batch.duplicates ?? '—'}
                  </small>
                  <code>{batch.id}</code>
                </div>
                {batch.deleted || batch.status === 'deleted' ? (
                  <Badge>已删除</Badge>
                ) : (
                  <button
                    className="button secondary small-button"
                    disabled={!!busy}
                    onClick={() => void previewDeletion(batch.id)}
                  >
                    查看删除影响
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty-copy spaced">当前关系暂无导入批次。</p>
        )}
        {notice && (
          <p className="success-note" role="status">
            {notice}
          </p>
        )}
        {impact && (
          <div className="deletion-review">
            <div className="card-title">
              <Icon name="file" size={18} />
              <h3>删除前核对影响</h3>
            </div>
            <p className="muted">批次 {impact.batch_id}</p>
            <dl className="impact-counts">
              {Object.entries(impact.counts).map(([name, count]) => (
                <div key={name}>
                  <dt>{countLabels[name] ?? name}</dt>
                  <dd>{count}</dd>
                </div>
              ))}
            </dl>
            {!!impact.revoked_dataset_ids?.length && (
              <p className="field-hint">
                将失效 {impact.revoked_dataset_ids.length} 个数据集、
                {impact.revoked_artifact_ids?.length ?? 0} 个模型产物和{' '}
                {impact.revoked_deployment_ids?.length ?? 0} 个部署版本。
              </p>
            )}
            {impact.warnings?.map((warning, index) => (
              <p className="warning" key={index}>
                {warning}
              </p>
            ))}
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={reviewed}
                onChange={(event) => setReviewed(event.target.checked)}
              />
              <span>
                我已核对本次删除影响，确认删除这批本地来源及其关联用途。已训练权重和已有备份不会自动遗忘。
              </span>
            </label>
            <div className="action-row">
              <button
                className="button danger"
                disabled={!reviewed || !!busy}
                onClick={() => void deleteBatch()}
              >
                确认删除此批次
              </button>
              <button
                className="button secondary"
                disabled={!!busy}
                onClick={() => setImpact(null)}
              >
                取消
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
