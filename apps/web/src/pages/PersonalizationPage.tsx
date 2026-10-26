import { useState } from 'react';
import type { Binding } from '../api';
import MemoryPanel from './MemoryPanel';
import StylePanel from './StylePanel';

export default function PersonalizationPage(props: {
  token: string;
  binding: Binding;
  onError: (error: unknown) => void;
}) {
  const [tab, setTab] = useState<'memory' | 'style'>('memory');
  return (
    <>
      <div className="page-tabs" role="group" aria-label="风格与记忆视图">
        <button
          aria-pressed={tab === 'memory'}
          className={tab === 'memory' ? 'selected' : ''}
          onClick={() => setTab('memory')}
        >
          关系记忆
        </button>
        <button
          aria-pressed={tab === 'style'}
          className={tab === 'style' ? 'selected' : ''}
          onClick={() => setTab('style')}
        >
          表达风格
        </button>
      </div>
      {tab === 'memory' ? <MemoryPanel {...props} /> : <StylePanel {...props} />}
    </>
  );
}
