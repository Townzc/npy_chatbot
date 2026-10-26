from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
text=(root/'DEVELOPMENT_PLAN.md').read_text(encoding='utf-8')
matches=list(re.finditer(r'^## (\d+)\. ', text, re.M))
sections={int(m.group(1)):text[m.start():matches[i+1].start() if i+1<len(matches) else len(text)].strip() for i,m in enumerate(matches)}
mapping={'product.md': [0, 1], 'architecture.md': [2, 4], 'contracts.md': [5, 12], 'data-and-training.md': [6, 7, 8], 'runtime-and-modes.md': [9, 10, 11], 'evaluation.md': [14], 'roadmap.md': [16], 'tasks.md': [17], 'open-source-and-ops.md': [3, 13, 15], 'sources.md': [19]}
for name,indexes in mapping.items():
    content='# '+name+'\n\n本文件是完整计划的按主题阅读副本。规范以 [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) 为准；来源见 [sources.md](sources.md)。修改计划时使用随包脚本重新生成这些副本。\n\n'+'\n\n'.join(sections[n] for n in indexes)+'\n'
    (root/'docs'/name).write_text(content,encoding='utf-8')
print('Updated',len(mapping),'plan reading copies')
