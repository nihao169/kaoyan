from typing import Literal
from pydantic import BaseModel, Field, model_validator


class QuestionCandidate(BaseModel):
    material_id: str
    knowledge: str = Field(min_length=1,max_length=200)
    kind: Literal['single','multiple','essay']
    prompt: str = Field(min_length=1,max_length=10000)
    options: dict[str,str] = Field(default_factory=dict,max_length=8)
    answer: list[str] = Field(default_factory=list,max_length=8)
    explanation: str = Field(min_length=1,max_length=30000)
    rubric: list[str] = Field(default_factory=list,max_length=30)
    quote: str = Field(min_length=8,max_length=24000)

    @model_validator(mode='after')
    def answer_matches(self):
        if self.kind=='essay':
            if not self.rubric:
                raise ValueError('分析题需要评分要点')
        elif len(self.options)<2 or not self.answer or len(set(self.answer))!=len(self.answer) or any(k not in self.options for k in self.answer):
            raise ValueError('答案和选项不匹配')
        elif self.kind=='single' and len(self.answer)!=1:
            raise ValueError('单选题只能有一个答案')
        return self
