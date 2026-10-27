import { useState } from 'react';
import { request, type Binding } from '../api';
import { Icon, Report } from '../components/ui';
import DataManagement from './DataManagement';

export default function ImportPanel({
  token,
  binding,
  onError,
}: {
  token: string;
  binding: Binding;
  onError: (e: unknown) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState('chatlab');
  const [account, setAccount] = useState('');
  const [owner, setOwner] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [mapping, setMapping] = useState('{}');
  const [conversationKind, setConversationKind] = useState<'' | 'private' | 'group'>('');
  const [preview, setPreview] = useState<unknown>(null);
  const [report, setReport] = useState<unknown>(null);
  const [busy, setBusy] = useState('');
  const [revision, setRevision] = useState(0);
  async function run(importNow: boolean) {
    if (!file) return;
    setBusy(importNow ? 'import' : 'inspect');
    const form = new FormData();
    form.set('file', file);
    form.set('format', format);
    form.set('source_account_id', account.trim());
    if (importNow) {
      form.set('persona_id', binding.persona_id);
      form.set('relationship_id', binding.relationship_id);
      form.set('owner_sender_id', owner.trim());
      form.set('confirmed_human', String(confirmed));
    }
    try {
      const parsed: unknown = JSON.parse(mapping);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
        throw new Error('映射配置必须是 JSON 对象。');
      const config = parsed as Record<string, unknown>;
      if (conversationKind) {
        if (config.conversation_kind && config.conversation_kind !== conversationKind)
          throw new Error('会话类型与自定义映射 JSON 不一致，请核对后重新预览。');
        config.conversation_kind = conversationKind;
      }
      form.set('mapping', JSON.stringify(config));
      const result = await request<unknown>(token, importNow ? '/imports' : '/imports/inspect', {
        method: 'POST',
        body: form,
      });
      if (importNow) {
        setReport(result);
        setRevision((previous) => previous + 1);
      } else {
        setPreview(result);
        setOwner('');
        setConfirmed(false);
      }
    } catch (e) {
      onError(e);
    } finally {
      setBusy('');
    }
  }
  const senders =
    preview && typeof preview === 'object' && 'senders' in preview && Array.isArray(preview.senders)
      ? (preview.senders as { id: string; name: string; source_account_id: string }[])
      : [];
  return (
    <>
      <div className="form-grid">
        <section className="panel form-panel">
          <div className="section-number">
            01 <span>选择已导出的记录</span>
          </div>
          <p className="muted">支持文件格式与实际兼容性以预览报告为准。</p>
          <label className="upload-box">
            <Icon name="import" size={30} />
            <strong>{file ? file.name : '选择聊天记录文件'}</strong>
            <span>JSON、JSONL 或 CSV · 不自动读取设备数据库</span>
            <input
              type="file"
              accept=".json,.jsonl,.csv,.bak"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setPreview(null);
                setReport(null);
                setConversationKind('');
                setMapping('{}');
                setOwner('');
                setConfirmed(false);
              }}
            />
          </label>
          <p className="muted">QQ .bak 仅能检查备份类型，尚不能直接解密导入。</p>
          <div className="form-row">
            <label>
              导入格式
              <select
                value={format}
                onChange={(e) => {
                  setFormat(e.target.value);
                  setPreview(null);
                  setReport(null);
                  setConversationKind('');
                  setMapping('{}');
                  setOwner('');
                  setConfirmed(false);
                }}
              >
                <option value="chatlab">ChatLab JSON / JSONL</option>
                <option value="qce">QCE 单文件 JSON（参考 v6.3.2）</option>
                <option value="csv_mapping">通用 CSV</option>
                <option value="canonical_jsonl">ChatTwin 规范 JSONL</option>
              </select>
            </label>
            <label>
              来源账号稳定 ID
              <input
                value={account}
                onChange={(e) => {
                  setAccount(e.target.value);
                  setPreview(null);
                }}
                placeholder="例如 demo_source_account"
              />
            </label>
          </div>
          {format === 'qce' && (
            <p className="field-hint">
              支持导出核心 0.1.0 的单文件 JSON。此字段不是 QCE 产品版本号；请保留导出程序版本。
              系统、撤回、非文字消息只保留预览，不作为训练目标。分块 JSONL 暂不支持。
            </p>
          )}
          <label>
            原会话类型
            <select
              value={conversationKind}
              onChange={(event) => {
                setConversationKind(event.target.value as typeof conversationKind);
                setPreview(null);
                setReport(null);
                setOwner('');
                setConfirmed(false);
              }}
            >
              <option value="">按文件声明；未声明为未知</option>
              <option value="private">我确认这批记录来自一对一私聊</option>
              <option value="group">这批记录来自群聊</option>
            </select>
          </label>
          <p className="field-hint">
            请按原会话事实选择。未声明类型的 CSV / 规范 JSONL
            默认保持未知，不进入私聊关系训练；群聊不会因指定私聊而改写原有声明。
          </p>
          <details className="mapping-options">
            <summary>自定义字段与时区（可选）</summary>
            <label>
              映射配置 JSON
              <textarea
                rows={5}
                value={mapping}
                onChange={(e) => {
                  setMapping(e.target.value);
                  setPreview(null);
                }}
                spellCheck={false}
              />
            </label>
            <p className="field-hint">
              默认 CSV 列：sender_id、occurred_at、text、conversation。可设置
              fields、timezone、time_unit 和 platform。也可显式填写
              conversation_kind，须与上方选择一致；可靠的规范 manifest
              可声明会话类型，服务会核对其哈希、数量和范围。
            </p>
          </details>
          <button
            className="button secondary"
            disabled={!file || !account.trim() || !!busy}
            onClick={() => void run(false)}
          >
            <Icon name="file" size={17} />
            {busy === 'inspect' ? '正在解析…' : '预览文件与发送者'}
          </button>
          {preview != null && <Report value={preview} />}
        </section>
        <section className="panel form-panel">
          <div className="section-number">
            02 <span>确认本人身份与用途</span>
          </div>
          <p className="muted">导出者不一定是训练目标。请从预览中的稳定 ID 明确选择本人。</p>
          <label>
            本人的原始 sender_id
            {senders.length ? (
              <select
                value={owner}
                onChange={(e) => {
                  setOwner(e.target.value);
                  setConfirmed(false);
                }}
              >
                <option value="">请选择本人身份，不按昵称自动判断</option>
                {senders.map((sender) => (
                  <option key={`${sender.source_account_id}:${sender.id}`} value={sender.id}>
                    {sender.name || sender.id} · {sender.id}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="从预览中复制稳定发送者 ID"
              />
            )}
          </label>
          <div className="scope-preview">
            <Icon name="lock" size={18} />
            <span>数据将进入当前选择的个人档案与关系空间。</span>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              我确认本次选定的本人记录由真人发出，允许用于风格与训练目标。
              <small>不确定时保持未勾选，记录仍可导入，但 unknown 不成为训练标签。</small>
            </span>
          </label>
          <button
            className="button primary"
            disabled={!preview || !owner.trim() || !!busy}
            onClick={() => void run(true)}
          >
            {busy === 'import' ? '正在导入…' : '确认身份并导入'}
            <Icon name="arrow" size={17} />
          </button>
          {report != null && <Report value={report} />}
          <div className="quiet-note">
            <Icon name="file" size={16} />
            <p>导入成功仅表示提供的文件已解析，不能证明历史完整。训练数据集仍需单独构建与检查。</p>
          </div>
        </section>
      </div>
      <DataManagement token={token} binding={binding} revision={revision} onError={onError} />
    </>
  );
}
