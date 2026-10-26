import { useCallback, useEffect, useState } from 'react';
import {
  download,
  post,
  request,
  type BackupEntry,
  type BackupReport,
  type BackupCreated,
  type DiagnosticsReport,
} from '../api';
import { Badge, Icon } from '../components/ui';
import BudgetPanel from './BudgetPanel';

type Backup = BackupEntry;
const countLabels: Record<string, string> = {
  personas: '个人档案',
  relationships: '关系空间',
  messages: '消息',
  message_uses: '用途映射',
  imports: '导入批次',
  import_batches: '导入批次',
  memories: '关系记忆',
  memory_items: '关系记忆',
  styles: '风格版本',
  style_profiles: '风格版本',
  datasets: '数据集',
  dataset_versions: '数据集',
  artifacts: '模型产物',
  model_artifacts: '模型产物',
  model_deployments: '模型部署',
  mode_sessions: '会话状态',
  outbox: '发送队列',
  jobs: '后台作业',
  audit_events: '审计记录',
  bindings: '会话绑定',
  inbound_events: '入站事件',
  identity_links: '身份映射',
  usage_records: '用量记录',
};

export default function OperationsPanel({
  token,
  personaId,
  onError,
}: {
  token: string;
  personaId?: string;
  onError: (error: unknown) => void;
}) {
  const [diagnostics, setDiagnostics] = useState<DiagnosticsReport | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [busy, setBusy] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState('');
  const [backupReport, setBackupReport] = useState<BackupReport | null>(null);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const result = await Promise.allSettled([
        request<DiagnosticsReport>(token, '/diagnostics', { signal }),
        request<Backup[]>(token, '/backups', { signal }),
      ]);
      if (signal?.aborted) return;
      if (result[0].status === 'fulfilled') setDiagnostics(result[0].value);
      else onError(result[0].reason);
      if (result[1].status === 'fulfilled') setBackups(result[1].value);
      else onError(result[1].reason);
    },
    [token, onError],
  );
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);
  async function createBackup() {
    if (!confirmed) return;
    setBusy('create');
    setNotice('');
    try {
      const result = await post<BackupCreated>(token, '/backups', {});
      setBackupReport(result.report);
      const next = await request<Backup[]>(token, '/backups');
      setBackups(next);
      setNotice(
        next.some((backup) => backup.id === result.id)
          ? '一致性备份已创建，可以下载并妥善保管。'
          : '备份请求已受理。完成后会出现在备份列表，可点击刷新查看。',
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function downloadBackup(backup: Backup) {
    setBusy(backup.id);
    try {
      await download(
        token,
        `/backups/${encodeURIComponent(backup.id)}/download`,
        `chattwin-backup-${backup.id}.zip`,
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  function downloadDiagnostics() {
    if (!diagnostics) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(diagnostics, null, 2)], { type: 'application/json' }),
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'chattwin-diagnostics.json';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const counts =
    diagnostics && typeof diagnostics.counts === 'object' && diagnostics.counts
      ? (diagnostics.counts as Record<string, unknown>)
      : {};
  return (
    <>
      {personaId && (
        <BudgetPanel key={personaId} token={token} personaId={personaId} onError={onError} />
      )}
      <div className="form-grid spaced-panel">
        <section className="panel form-panel">
          <div className="panel-header plain">
            <h2>脱敏诊断</h2>
            <button className="text-button" onClick={() => void refresh()}>
              刷新
            </button>
          </div>
          <p className="muted">
            查看服务返回的状态与计数。诊断报告由后端过滤，不包含聊天正文、密钥或模型权重。
          </p>
          {Object.keys(counts).length ? (
            <dl className="settings-list">
              {Object.entries(counts).map(([key, value]) => (
                <div key={key}>
                  <dt>{countLabels[key] ?? key}</dt>
                  <dd>
                    {typeof value === 'number' ? value.toLocaleString('zh-CN') : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {diagnostics &&
            Boolean(diagnostics.checks) &&
            typeof diagnostics.checks === 'object' &&
            diagnostics.checks !== null &&
            'foreign_keys_ok' in diagnostics.checks && (
              <Badge tone={diagnostics.checks.foreign_keys_ok ? 'green' : 'amber'}>
                {diagnostics.checks.foreign_keys_ok ? '数据库外键检查通过' : '数据库外键检查未通过'}
              </Badge>
            )}
          <div className="action-row">
            <button
              className="button secondary"
              disabled={!diagnostics}
              onClick={downloadDiagnostics}
            >
              <Icon name="import" size={16} />
              下载诊断报告
            </button>
          </div>
          {diagnostics && (
            <details className="report">
              <summary>查看脱敏诊断内容</summary>
              <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
            </details>
          )}
          <div className="notice spaced">
            <Icon name="lock" size={18} />
            <p>下载后由你决定是否分享；本应用不会自动上传诊断报告。</p>
          </div>
        </section>
        <section className="panel form-panel">
          <div className="card-title">
            <Icon name="file" />
            <h2>本地一致性备份</h2>
          </div>
          <p className="muted">
            备份未加密，包含数据库、引用的数据集和模型 manifest。QQ
            会话、访问凭证和模型权重需分别保管，不随此备份复制。
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>我知道备份包含私人聊天与训练数据，并会保存在私有位置。</span>
          </label>
          <button
            className="button primary"
            disabled={!confirmed || !!busy}
            onClick={() => void createBackup()}
          >
            {busy === 'create' ? '正在创建一致性备份…' : '创建本地备份'}
          </button>
          {notice && (
            <p className="success-note" role="status">
              {notice}
            </p>
          )}
          {backupReport && (
            <div className="backup-receipt">
              <div className="mini-metrics">
                <div>
                  <small>备份文件</small>
                  <strong>{backupReport.files_count}</strong>
                </div>
                <div>
                  <small>大小 MiB</small>
                  <strong>{(backupReport.bytes / 1024 / 1024).toFixed(2)}</strong>
                </div>
                <div>
                  <small>忽略失效数据集</small>
                  <strong>{backupReport.revoked_datasets_omitted}</strong>
                </div>
              </div>
              <details className="compact-details">
                <summary>本次备份未包含的内容</summary>
                <ul className="exclusion-list">
                  {backupReport.excluded.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </details>
            </div>
          )}
          {backups.length ? (
            <ul className="backup-list">
              {backups.map((backup) => (
                <li key={backup.id}>
                  <div>
                    <strong>{new Date(backup.created_at).toLocaleString('zh-CN')}</strong>
                    <small>{(backup.bytes / 1024 / 1024).toFixed(2)} MiB</small>
                  </div>
                  <button
                    className="button secondary small-button"
                    disabled={!!busy}
                    onClick={() => void downloadBackup(backup)}
                  >
                    下载备份
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-copy spaced">尚无本地备份。</p>
          )}
          <details className="compact-details">
            <summary>恢复到新的空目录</summary>
            <p className="field-hint">
              先下载并解压备份，停止旧实例后，在终端检查并恢复到新的空目录。恢复后的会话保持停止，需重新核对账号和模型。
            </p>
            <pre className="command-example">
              {
                'uv run chattwin backup inspect BACKUP_DIRECTORY\nuv run chattwin backup restore BACKUP_DIRECTORY NEW_EMPTY_DIRECTORY'
              }
            </pre>
            <p className="field-hint">
              请将大写占位符替换为私有目录的实际路径。网页不会覆盖当前运行的数据目录。
            </p>
          </details>
        </section>
      </div>
    </>
  );
}
