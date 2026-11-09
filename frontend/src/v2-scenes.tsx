import { Radio } from 'antd';

export const learningScenes = {
  chapter: { title: '首次学习', description: '第一次学这门课，和助教一起建立理解。' },
  final: { title: '期末复习', description: '我已经学过，想按考试范围查漏补缺。' },
  kaoyan: { title: '考研学习', description: '带上目标与考试范围，和助教一起准备。' },
};

export type LearningScene = keyof typeof learningScenes;

function sceneKey(userId: string, projectId: string) {
  return `zhixing.learning-scene:${userId}:${projectId}`;
}

export function readLearningScene(userId: string, projectId: string): LearningScene | undefined {
  try {
    const scene = localStorage.getItem(sceneKey(userId, projectId));
    if (scene === 'chapter' || scene === 'final' || scene === 'kaoyan') return scene;
  } catch {
    // The project remains usable when browser storage is unavailable.
  }
}

export function saveLearningScene(userId: string, projectId: string, scene: LearningScene) {
  try {
    localStorage.setItem(sceneKey(userId, projectId), scene);
    return true;
  } catch {
    return false;
  }
}

export function LearningSceneOptions({ value, onChange }: {
  value?: LearningScene;
  onChange: (scene: LearningScene) => void;
}) {
  return <Radio.Group className="learning-scene-options" aria-label="学习场景" value={value}
    onChange={event => onChange(event.target.value)}>
    {(Object.keys(learningScenes) as LearningScene[]).map(scene => <Radio key={scene} value={scene}>
      <strong>{learningScenes[scene].title}</strong>
      <span>{learningScenes[scene].description}</span>
    </Radio>)}
  </Radio.Group>;
}

export const politicsPracticeNotice = '现有 AI 出题和分析题评价采用考研政治规则。';
