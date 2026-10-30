import re
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal

class ProfilePatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    college:Literal['SAI','MARX','CSE','CYBER']|None=None
    program_level:Literal['undergraduate','master','doctor']|None=None
    study_mode:Literal['full_time','part_time']|None=None
    degree_type:Literal['academic','professional']|None=None
    cohort_year:int|None=Field(None,ge=2000,le=2040)
    year_of_study:int|None=Field(None,ge=1,le=10)
    class_type:Literal['ordinary','self_strength']|None=None
    academic_rank_pct:float|None=Field(None,ge=0,le=100)
    comprehensive_rank_pct:float|None=Field(None,ge=0,le=100)
    achievement_eligible:bool|None=None
    has_exclusion:bool|None=None
    previous_leijun:bool|None=None
    another_special_award:bool|None=None
    english_eligible:bool|None=None
    midterm_result:Literal['excellent','good','pass','fail']|None=None
    major:str|None=Field(None,max_length=80)
    achievements:str|None=Field(None,max_length=600)

def extract(text):
    p={}
    # Identity facts must be a student statement, rather than a policy title in a question.
    clauses=re.split(r'[，,。；;！？?\n]',text)
    identity=' '.join(c for c in clauses if re.search(r'(?:我是|本人是|我就读|我在|我读|我为|我目前|我现在|我的学院)',c))
    if re.search(r'马克思主义学院|马院',identity):p['college']='MARX'
    elif '人工智能学院' in identity:p['college']='SAI'
    elif '计算机学院' in identity:p['college']='CSE'
    elif '网络安全学院' in identity:p['college']='CYBER'
    if re.search(r'本科|大[一二三四]',identity):p['program_level']='undergraduate'
    elif re.search(r'博士|博[一二三四]',identity):p['program_level']='doctor'
    elif re.search(r'硕士|研[一二三]',identity):p['program_level']='master'
    cn={'一':1,'二':2,'三':3,'四':4}
    m=re.search(r'[大研博]([一二三四])',identity)
    if m:p['year_of_study']=cn[m[1]]
    m=re.search(r'(20\d{2})级',identity)
    if m:p['cohort_year']=int(m[1])
    if '非全日制' in identity:p['study_mode']='part_time'
    elif '全日制' in identity:p['study_mode']='full_time'
    if '自强班' in identity:p['class_type']='self_strength'
    elif '普通班' in identity:p['class_type']='ordinary'
    if re.search(r'学术(?:学位|型)?硕士|学硕',identity):p['degree_type']='academic'
    elif re.search(r'专业学位|专硕',identity):p['degree_type']='professional'
    m=re.search(r'我的专业(?:是|为|[:：])\s*([^，,。；;！？?\n]{1,80})',text)
    if m:p['major']=m[1].strip()
    achievements=[c.strip() for c in clauses if re.search(r'我(?:已|曾)?(?:发表|获得|获过|完成|有一|有两|有三)',c)]
    if achievements:p['achievements']='；'.join(achievements)[:600]
    for field,pattern in [('academic_rank_pct',r'(?:学习成绩|学习排名|成绩排名)[^\d%]{0,8}(\d+(?:\.\d+)?)\s*%'),('comprehensive_rank_pct',r'(?:综合测评|综测)[^\d%]{0,8}(\d+(?:\.\d+)?)\s*%')]:
        m=re.search(pattern,text)
        if m and 0<=float(m[1])<=100:p[field]=float(m[1])
    if re.search(r'没有挂科|无不及格',text):p['_no_failed_courses']=True
    if re.search(r'中期考核.{0,3}(优秀|良好|合格|不合格)',text):
        value=re.search(r'中期考核.{0,3}(优秀|良好|不合格|合格)',text)[1]
        p['midterm_result']={'优秀':'excellent','良好':'good','合格':'pass','不合格':'fail'}[value]
    return p

LABELS={'college':'学院','program_level':'学历层次','study_mode':'培养方式','degree_type':'学位类型','cohort_year':'入学年份','year_of_study':'当前年级','class_type':'班型','academic_rank_pct':'学习成绩排名百分比','comprehensive_rank_pct':'综合测评排名百分比','achievement_eligible':'成果是否符合政策分支','has_exclusion':'是否存在通知列举的禁止参评情形','previous_leijun':'是否曾获本奖学金','another_special_award':'本年度是否已获其他专项奖学金','english_eligible':'外语是否满足对应条件','midterm_result':'中期考核结果'}
VALUES={'SAI':'人工智能学院','MARX':'马克思主义学院','CSE':'计算机学院','CYBER':'国家网络安全学院','undergraduate':'本科','master':'硕士','doctor':'博士','full_time':'全日制','part_time':'非全日制','academic':'学术学位','professional':'专业学位','ordinary':'普通班','self_strength':'人工智能自强班','excellent':'优秀','good':'良好','pass':'合格','fail':'不合格'}
LABELS.update(major='专业',achievements='成果自述')

