import { useCallback, useEffect, useState } from 'react';
import {
  download,
  post,
  request,
  scopeQuery,
  type Binding,
  type WorkspaceState,
  type JobView,
  type JobLogs,
  type TrainingJobRequest,
  type TrainingEnvironment,
} from '../api';
import { Badge, Icon, Report } from '../components/ui';

interface Dataset {
  id: string;
  dataset_hash: string;
  created_at: string;
  status?: string;
  path?: string;
  counts: { train: number; validation: number; test: number };
  confidence?: string;
}
type Environment = TrainingEnvironment;
type TrainingJob = JobView;
type TrainingConfig = Required<
  Omit<TrainingJobRequest, 'dataset_id' | 'persona_id' | 'relationship_id'>
>;
interface DatasetSample {
  id: string;
  messages: { role: string; content: string }[];
  target_index: number;
}
interface DatasetPreview {
  examples: { train: DatasetSample[]; validation: DatasetSample[]; test: DatasetSample[] };
}
const initialConfig: TrainingConfig = {
  precision: 'bfloat16',
  rank: 8,
  alpha: 16,
  dropout: 0.05,
  max_sequence_length: 1024,
  batch_size: 1,
  gradient_accumulation: 4,
  gradient_checkpointing: false,
  learning_rate: 0.0002,
  epochs: 1,
  max_steps: 100,
  seed: 42,
  allow_model_download: false,
};
const jobLabels: Record<string, string> = {
  queued: '等待执行',
  validating: '环境与数据预检',
  running: '训练中',
  succeeded: '训练完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
};
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'interrupted']);

export default function TrainingPanel({
  token,
  binding,
  state,
  onError,
}: {
  token: string;
  binding: Binding;
  state: WorkspaceState;
  onError: (error: unknown) => void;
}) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState('');
  const [environment, setEnvironment] = useState<Environment | null>(null);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [config, setConfig] = useState<TrainingConfig>(initialConfig);
  const [busy, setBusy] = useState('');
  const [report, setReport] = useState<unknown>(null);
  const [packageConfirmed, setPackageConfirmed] = useState(false);
  const [samples, setSamples] = useState<DatasetPreview | null>(null);
  const [sampleSplit, setSampleSplit] = useState<'train' | 'validation' | 'test'>('train');
  const [notice, setNotice] = useState('');
  const [logs, setLogs] = useState<Record<string, JobLogs['events']>>({});
  const query = scopeQuery(binding);
  const dataset = datasets.find((item) => item.id === datasetId);
  const refreshDatasets = useCallback(
    async (signal?: AbortSignal) => {
      const result = await request<Dataset[]>(token, `/datasets${query}`, { signal });
      if (signal?.aborted) return;
      setDatasets(result);
      setDatasetId((previous) =>
        result.some((item) => item.id === previous && item.status !== 'revoked')
          ? previous
          : (result.find((item) => item.status !== 'revoked')?.id ?? ''),
      );
    },
    [token, query],
  );
  const refreshEnvironment = useCallback(
    async (signal?: AbortSignal) => {
      const result = await request<Environment>(token, '/training-environment', { signal });
      if (!signal?.aborted) setEnvironment(result);
    },
    [token],
  );
  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled([
      refreshDatasets(controller.signal),
      refreshEnvironment(controller.signal),
    ]).then((results) => {
      if (!controller.signal.aborted)
        results.forEach((result) => {
          if (result.status === 'rejected') onError(result.reason);
        });
    });
    return () => controller.abort();
  }, [refreshDatasets, refreshEnvironment, onError]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      let delay = 6000;
      try {
        const result = await request<TrainingJob[]>(token, `/training-jobs${query}`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setJobs(result);
          delay = result.some((job) => !terminal.has(job.status)) ? 2500 : 6000;
        }
      } catch (error) {
        if (!controller.signal.aborted) onError(error);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, delay);
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [token, query, onError]);
  async function build() {
    setBusy('build');
    setNotice('');
    try {
      const result = await post<Dataset>(token, '/datasets', {
        persona_id: binding.persona_id,
        relationship_id: binding.relationship_id,
      });
      setReport(result);
      setSamples(null);
      await refreshDatasets();
      setDatasetId(result.id);
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  const body: TrainingJobRequest = {
    dataset_id: datasetId,
    persona_id: binding.persona_id,
    relationship_id: binding.relationship_id,
    ...config,
  };
  async function previewSamples() {
    if (!dataset) return;
    setBusy('preview');
    try {
      setSamples(
        await request<DatasetPreview>(
          token,
          `/datasets/${encodeURIComponent(dataset.id)}/preview${query}`,
        ),
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function start() {
    if (!dataset || dataset.status === 'revoked') return;
    setBusy('start');
    setNotice('');
    try {
      const job = await post<TrainingJob>(token, '/training-jobs', body);
      setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)]);
      setNotice(
        `作业已进入队列。当前状态：${jobLabels[job.status] ?? job.status}；只有实际训练和产物验证成功才会显示完成。`,
      );
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function exportBundle() {
    if (!dataset || !packageConfirmed) return;
    setBusy('export');
    setNotice('');
    try {
      await download(token, '/training-bundles', `chattwin-training-${dataset.id}.zip`, body);
      setNotice('训练包已下载到浏览器的下载目录。请在自有、已验证的 GPU 环境运行包内启动器。');
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function cancel(job: TrainingJob) {
    setBusy(job.id);
    try {
      const updated = await post<TrainingJob>(
        token,
        `/training-jobs/${encodeURIComponent(job.id)}/cancel`,
        {},
      );
      setJobs((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
    } catch (error) {
      onError(error);
    } finally {
      setBusy('');
    }
  }
  async function viewLogs(job: TrainingJob) {
    try {
      const result = await request<JobLogs>(token, `/jobs/${encodeURIComponent(job.id)}/logs`);
      setLogs((previous) => ({ ...previous, [job.id]: result.events }));
    } catch (error) {
      onError(error);
    }
  }
  function numberField(
    key: Exclude<
      keyof TrainingConfig,
      'precision' | 'allow_model_download' | 'gradient_checkpointing'
    >,
    label: string,
    minimum: number,
    maximum: number,
    step = 1,
  ) {
    return (
      <label key={key}>
        {label}
        <input
          type="number"
          min={minimum}
          max={maximum}
          step={step}
          value={config[key]}
          onChange={(event) =>
            setConfig((previous) => ({ ...previous, [key]: Number(event.target.value) }))
          }
        />
      </label>
    );
  }
  const canTrain =
    !!dataset &&
    dataset.status !== 'revoked' &&
    dataset.counts.train > 0 &&
    !!environment?.supports_reference_training;
  const precisionSupported = config.precision !== 'bfloat16' || !!environment?.cuda_bf16_supported;
  return (
    <>
      <div className="training-steps">
        <div>
          <span>01</span>
          <strong>确认本人记录</strong>
          <small>只选择已确认的人类发言</small>
        </div>
        <div>
          <span>02</span>
          <strong>冻结数据集</strong>
          <small>完整片段划分后再构造样本</small>
        </div>
        <div>
          <span>03</span>
          <strong>真实 LoRA 训练</strong>
          <small>独立环境执行并保存参数</small>
        </div>
        <div>
          <span>04</span>
          <strong>重载与对照验证</strong>
          <small>评测通过后再决定启用</small>
        </div>
      </div>
      <div className="form-grid">
        <section className="panel form-panel">
          <div className="card-title">
            <Icon name="file" />
            <h2>选择冻结的数据集</h2>
          </div>
          <p className="muted">
            每个快照保留身份、来源、划分与哈希。删除来源后失效的数据集不能继续用于训练。
          </p>
          <label>
            当前关系的数据集
            <select
              value={datasetId}
              onChange={(event) => {
                setDatasetId(event.target.value);
                setPackageConfirmed(false);
                setSamples(null);
              }}
            >
              <option value="">请选择或先构建数据集</option>
              {datasets.map((item) => (
                <option key={item.id} value={item.id} disabled={item.status === 'revoked'}>
                  {new Date(item.created_at).toLocaleString('zh-CN')} · 训练 {item.counts.train} /
                  验证 {item.counts.validation} / 测试 {item.counts.test}
                  {item.status === 'revoked' ? ' · 已失效' : ''}
                </option>
              ))}
            </select>
          </label>
          <button className="button secondary" disabled={!!busy} onClick={() => void build()}>
            <Icon name="plus" size={16} />
            {busy === 'build' ? '正在构建…' : '从当前记录构建新快照'}
          </button>
          {dataset && (
            <div className="dataset-summary">
              <div className="mini-metrics">
                <div>
                  <small>训练</small>
                  <strong>{dataset.counts.train}</strong>
                </div>
                <div>
                  <small>验证</small>
                  <strong>{dataset.counts.validation}</strong>
                </div>
                <div>
                  <small>测试</small>
                  <strong>{dataset.counts.test}</strong>
                </div>
              </div>
              <small>数据集版本</small>
              <code>{dataset.id}</code>
              <small>内容哈希</small>
              <code>{dataset.dataset_hash}</code>
              {dataset.confidence && <p className="field-hint">评测可信度：{dataset.confidence}</p>}
            </div>
          )}
          {dataset && (
            <button
              className="text-button spaced"
              disabled={!!busy || dataset.status === 'revoked'}
              onClick={() => void previewSamples()}
            >
              预览样本与训练目标
            </button>
          )}
          {samples && (
            <div className="sample-preview">
              <div className="page-tabs" role="group" aria-label="样本划分">
                {(['train', 'validation', 'test'] as const).map((split) => (
                  <button
                    key={split}
                    className={sampleSplit === split ? 'selected' : ''}
                    aria-pressed={sampleSplit === split}
                    onClick={() => setSampleSplit(split)}
                  >
                    {{ train: '训练', validation: '验证', test: '测试' }[split]}
                  </button>
                ))}
              </div>
              <p className="field-hint">
                每组最多显示 5 条。只有标记的当前本人回复计算训练 loss，历史上下文不计算。
              </p>
              {samples.examples[sampleSplit].length ? (
                samples.examples[sampleSplit].map((sample) => (
                  <article key={sample.id}>
                    {sample.messages.map((turn, index) => (
                      <div
                        className={index === sample.target_index ? 'target-turn' : ''}
                        key={index}
                      >
                        <small>
                          {index === sample.target_index
                            ? '当前本人目标'
                            : turn.role === 'assistant'
                              ? '历史本人上下文'
                              : turn.role === 'system'
                                ? '系统上下文'
                                : '对方上下文'}
                        </small>
                        <p>{turn.content}</p>
                      </div>
                    ))}
                  </article>
                ))
              ) : (
                <p className="empty-copy">此划分没有样本。</p>
              )}
            </div>
          )}
          {report != null && <Report value={report} />}
        </section>
        <section className="panel form-panel training-status">
          <div className="panel-header plain">
            <Badge tone={environment?.supports_reference_training ? 'green' : 'amber'}>
              {environment?.supports_reference_training ? 'GPU 基础环境可用' : 'GPU 训练条件待满足'}
            </Badge>
            <button
              className="text-button"
              onClick={() => void refreshEnvironment().catch(onError)}
            >
              重新检测
            </button>
          </div>
          <h2>先检查实际训练环境</h2>
          <p>
            {environment
              ? `${environment.platform} · Python ${environment.python_version || '未就绪'}`
              : state.training.detail}
          </p>
          <dl className="settings-list">
            <div>
              <dt>独立 Python</dt>
              <dd>{environment ? (environment.python_available ? '可用' : '未配置') : '检测中'}</dd>
            </div>
            <div>
              <dt>训练依赖</dt>
              <dd>{environment?.dependencies_available ? '可用' : '未验证'}</dd>
            </div>
            <div>
              <dt>CUDA</dt>
              <dd>{environment?.cuda_available ? '可用' : '不可用'}</dd>
            </div>
            <div>
              <dt>BF16 支持</dt>
              <dd>{environment?.cuda_bf16_supported ? '可用' : '未通过'}</dd>
            </div>
          </dl>
          {environment?.cuda_devices?.map((device) => (
            <p className="field-hint" key={device.index}>
              GPU {device.index} · {device.name} · 空闲{' '}
              {(device.free_memory_bytes / 1024 ** 3).toFixed(1)} /{' '}
              {(device.total_memory_bytes / 1024 ** 3).toFixed(1)} GiB
              {device.index === environment.active_cuda_device ? ' · 当前训练用卡' : ''}
            </p>
          ))}
          {environment?.blockers.map((blocker) => (
            <p className="warning" key={blocker}>
              {blocker}
            </p>
          ))}
          <p className="fine-print">
            缺少 GPU 时仍可导出训练包。环境检测不会下载模型；tiny smoke
            不代表参考底座训练或聊天质量通过。
          </p>
          {environment?.reference_model && (
            <details className="compact-details">
              <summary>固定底座与模板</summary>
              <code>{environment.reference_model.id}</code>
              <p className="field-hint">revision: {environment.reference_model.revision}</p>
              <p className="field-hint">
                template: {environment.reference_model.chat_template_hash}
              </p>
            </details>
          )}
        </section>
      </div>
      <section className="panel form-panel spaced-panel">
        <div className="card-title">
          <Icon name="train" />
          <h2>配置训练与导出</h2>
        </div>
        <div className="form-row">
          <label>
            精度
            <select
              value={config.precision}
              onChange={(event) =>
                setConfig((previous) => ({
                  ...previous,
                  precision: event.target.value as TrainingConfig['precision'],
                }))
              }
            >
              <option value="bfloat16">BF16</option>
              <option value="float16">FP16</option>
            </select>
          </label>
          {numberField('max_steps', '最大训练步数', 1, 1000000)}
          {numberField('rank', 'LoRA rank', 1, 128)}
          {numberField('max_sequence_length', '最长序列', 16, 32768)}
        </div>
        <details className="compact-details">
          <summary>高级参数</summary>
          <div className="config-fields">
            {numberField('alpha', 'LoRA alpha', 1, 1024)}
            {numberField('dropout', 'Dropout', 0, 0.99, 0.01)}
            {numberField('batch_size', 'Batch size', 1, 128)}
            {numberField('gradient_accumulation', '梯度累积', 1, 1024)}
            {numberField('learning_rate', '学习率', 0.000001, 0.1, 0.00001)}
            {numberField('epochs', 'Epochs', 1, 100)}
            {numberField('seed', '随机种子', 0, 2147483647)}
          </div>
        </details>
        <div className="action-row">
          <button
            className="button secondary small-button"
            onClick={() => {
              setConfig((previous) => ({
                ...previous,
                precision: 'bfloat16',
                rank: 8,
                alpha: 16,
                max_sequence_length: 512,
                batch_size: 1,
                gradient_accumulation: 4,
                gradient_checkpointing: true,
                max_steps: 2,
                epochs: 2,
              }));
              setNotice(
                '已填入单卡 4090 的 2 步试运行配置，尚未开始训练。实际显存需求以训练报告为准。',
              );
            }}
          >
            使用 4090 试运行配置
          </button>
          <span className="field-hint">一次作业使用一张 GPU；多张卡的显存不会自动合并。</span>
        </div>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={config.gradient_checkpointing}
            onChange={(event) =>
              setConfig((previous) => ({
                ...previous,
                gradient_checkpointing: event.target.checked,
              }))
            }
          />
          <span>启用梯度检查点：减少训练显存占用，会增加计算时间。</span>
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={config.allow_model_download}
            onChange={(event) =>
              setConfig((previous) => ({ ...previous, allow_model_download: event.target.checked }))
            }
          />
          <span>允许训练 worker 下载固定版本的底座与分词器。默认只使用本机缓存。</span>
        </label>
        <div className="training-action-grid">
          <div>
            <button
              className="button primary"
              disabled={!!busy || !canTrain || !precisionSupported}
              onClick={() => void start()}
            >
              {busy === 'start' ? '正在创建作业…' : '开始真实 LoRA 训练'}
              <Icon name="arrow" size={16} />
            </button>
            {!canTrain && (
              <p className="field-hint">需选择有效且非空的数据集，并通过参考底座 GPU 环境检测。</p>
            )}
          </div>
          <div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={packageConfirmed}
                onChange={(event) => setPackageConfirmed(event.target.checked)}
              />
              <span>
                我知道下载包包含所选数据集的私有聊天训练样本、manifest 和训练代码；不包含 QQ
                凭证或模型密钥。
              </span>
            </label>
            <button
              className="button secondary"
              disabled={!!busy || !dataset || dataset.status === 'revoked' || !packageConfirmed}
              onClick={() => void exportBundle()}
            >
              <Icon name="import" size={16} />
              {busy === 'export' ? '正在打包…' : '下载独立训练包'}
            </button>
          </div>
        </div>
        {notice && (
          <p className="success-note" role="status">
            {notice}
          </p>
        )}
      </section>
      <section className="panel form-panel spaced-panel">
        <div className="panel-header plain">
          <h2>训练作业</h2>
          <span className="count">{jobs.length}</span>
        </div>
        {jobs.length ? (
          <div className="job-list">
            {jobs.map((job) => (
              <article key={job.id} className="job-card">
                <div className="job-heading">
                  <div>
                    <strong>{jobLabels[job.status] ?? job.status}</strong>
                    <small>
                      {new Date(job.created_at).toLocaleString('zh-CN')} · {job.phase || '等待调度'}
                    </small>
                  </div>
                  <Badge
                    tone={
                      job.status === 'succeeded'
                        ? 'green'
                        : job.status === 'failed' || job.status === 'interrupted'
                          ? 'amber'
                          : 'neutral'
                    }
                  >
                    {job.cancel_requested && !terminal.has(job.status)
                      ? '正在取消'
                      : (jobLabels[job.status] ?? job.status)}
                  </Badge>
                </div>
                <progress
                  aria-label="训练进度"
                  value={Math.min(1, Math.max(0, job.progress))}
                  max={1}
                />
                <div className="job-meta">
                  <span>
                    Step {job.step ?? 0} ·{' '}
                    {(Math.min(1, Math.max(0, job.progress)) * 100).toFixed(0)}%
                  </span>
                  <span>{job.loss == null ? '尚无 loss' : `Loss ${job.loss.toFixed(4)}`}</span>
                </div>
                {job.error_summary && (
                  <p className="error">
                    {job.error_code && <strong>{job.error_code} · </strong>}
                    {job.error_summary}
                  </p>
                )}
                {job.artifact_ready && (
                  <div className="success-note">
                    <strong>模型产物已保存</strong>
                    <p>接下来可在模型版本页登记、测试并明确启用。</p>
                    <code>{job.output_path}</code>
                  </div>
                )}
                <div className="action-row">
                  <button className="text-button" onClick={() => void viewLogs(job)}>
                    查看作业事件
                  </button>
                  {!terminal.has(job.status) && (
                    <button
                      className="button secondary small-button"
                      disabled={busy === job.id || job.cancel_requested}
                      onClick={() => void cancel(job)}
                    >
                      取消作业
                    </button>
                  )}
                </div>
                {logs[job.id] && (
                  <ol className="job-events">
                    {logs[job.id].map((event, index) => (
                      <li key={`${event.at}:${index}`}>
                        <time>{new Date(event.at).toLocaleTimeString('zh-CN')}</time>
                        <strong>{event.event}</strong>
                        <span>{event.detail}</span>
                      </li>
                    ))}
                  </ol>
                )}
                <details className="compact-details">
                  <summary>作业与数据版本</summary>
                  <code>{job.id}</code>
                  <p className="field-hint">数据集：{job.dataset_id}</p>
                  <p className="field-hint">
                    心跳：{job.heartbeat ? new Date(job.heartbeat).toLocaleString('zh-CN') : '尚无'}
                  </p>
                </details>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-copy spaced">
            当前关系没有训练作业。构建数据集后，可在支持的 GPU 环境开始训练，或先下载训练包。
          </p>
        )}
      </section>
    </>
  );
}
