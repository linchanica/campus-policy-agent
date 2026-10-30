from datetime import datetime,date
from decimal import Decimal
from .config import TZ

def combine(op,values):
    if op=='all':return 'fail' if 'fail' in values else ('unknown' if 'unknown' in values else 'pass')
    if op=='any':return 'pass' if 'pass' in values else ('unknown' if 'unknown' in values else 'fail')
    if op=='not':return {'pass':'fail','fail':'pass','unknown':'unknown'}[values[0]]
    raise ValueError('Unsupported rule operation')

def evaluate(node,profile):
    op=node['op']
    if op in {'all','any','not'}:return combine(op,[evaluate(x,profile) for x in node['children']])
    value=profile.get(node['field'])
    if value is None:return 'unknown'
    expected=node.get('value')
    if op=='eq':ok=value==expected
    elif op=='in':ok=value in expected
    elif op=='lte':ok=Decimal(str(value))<=Decimal(str(expected))
    elif op=='gte':ok=Decimal(str(value))>=Decimal(str(expected))
    else:raise ValueError('Unsupported comparison')
    return 'pass' if ok else 'fail'

def window(topic,at):
    if topic in {'lei_undergrad','lei_graduate'}:
        deadline=datetime(2026,10,26,17,tzinfo=TZ)
        state='closed' if at>deadline else ('open_by_original_notice' if at<deadline else 'boundary_uncertain')
        return {'state':state,'raw':'2026年10月26日17:00前','stage':'个人申报','note':'当前仅有原通知，未取得延期或补报依据。'}
    if topic in {'midterm','phd'}:
        day=date(2026,10,30)
        state='closed' if at.date()>day else ('boundary_uncertain' if at.date()==day else 'open_by_original_notice')
        return {'state':state,'raw':'2026年10月30日前','stage':'个人申请','note':'原文未给具体时刻，当天边界需向经办方确认。'}
    if topic=='phd_marx':
        day=date(2026,10,26)
        state='closed' if at.date()>day else ('boundary_uncertain' if at.date()==day else 'open_by_original_notice')
        return {'state':state,'raw':'2026年10月26日前','stage':'个人申请','note':'整体考核至11月9日，不能作为个人申请截止时间。'}
    return {'state':'unknown','raw':None,'stage':'待确定','note':'尚未定位当前事项的办理时限。'}

def checks(topic,p):
    def leaf(field,op,value):return {'field':field,'op':op,'value':value}
    if topic=='lei_undergrad':
        threshold=30 if p.get('class_type')=='self_strength' and p.get('college')=='SAI' else 20
        ranks='unknown' if not p.get('class_type') or (p.get('class_type')=='self_strength' and p.get('college')!='SAI') else evaluate({'op':'all','children':[leaf('academic_rank_pct','lte',threshold),leaf('comprehensive_rank_pct','lte',threshold)]},p)
        return [
            ('学院范围',evaluate(leaf('college','in',['SAI','CSE','CYBER']),p),['college'],'计算机学院、国家网络安全学院、人工智能学院。','评选对象'),
            ('本科身份',evaluate(leaf('program_level','eq','undergraduate'),p),['program_level'],'面向本科生。','评选对象'),
            ('全日制二年级及以上',evaluate({'op':'all','children':[leaf('study_mode','eq','full_time'),leaf('year_of_study','gte',2)]},p),['study_mode','year_of_study'],'须为全日制二年级及以上本科生。','评选对象'),
            ('学习与综测双排名',ranks,['class_type','academic_rank_pct','comprehensive_rank_pct'],f'普通情况两项均前20%；人工智能自强班两项均前30%。当前分支门槛为{threshold}%。','学习成绩以及综合测评'),
            ('成果条件',evaluate(leaf('achievement_eligible','eq',True),p),['achievement_eligible'],'竞赛、科研、社会实践至少符合一类；成果认定需核对具体条款。','还应满足以下条件之一'),
            ('无禁止参评情形',evaluate(leaf('has_exclusion','eq',False),p),['has_exclusion'],'逐项检查处分、学术不端、课程不及格等通知列明情况。','不能参加'),
            ('曾获奖与专项奖互斥',evaluate({'op':'all','children':[leaf('previous_leijun','eq',False),leaf('another_special_award','eq',False)]},p),['previous_leijun','another_special_award'],'在校期间只能获评一次，与本年度其他专项奖学金不可兼得。','不可兼得')]
    if topic=='lei_graduate':
        return [('学院范围',evaluate(leaf('college','in',['SAI','CSE','CYBER']),p),['college'],'面向通知列明三个学院。','评选对象'),('2026级博士新生',evaluate({'op':'all','children':[leaf('program_level','eq','doctor'),leaf('cohort_year','eq',2026),leaf('study_mode','eq','full_time')]},p),['program_level','cohort_year','study_mode'],'还须为首次取得博士学籍的直博或硕博连读新生；具体培养路径需人工核实。','首次取得博士生学籍')]
    base=[('学院',evaluate(leaf('college','eq','MARX' if topic=='phd_marx' else 'SAI'),p),['college'],'按对应学院的实施安排办理。','通知'),('学术学位硕士',evaluate({'op':'all','children':[leaf('program_level','eq','master'),leaf('degree_type','eq','academic')]},p),['program_level','degree_type'],'学术学位硕士，与专业学位区分。','学术学位硕士研究生')]
    base.append(('入学年份',evaluate(leaf('cohort_year','in',[2025] if topic=='midterm' else [2024,2025]),p),['cohort_year'],'中期考核为2025级；本轮硕博连读对象为2024、2025级。','考核对象'))
    if topic!='midterm':
        base.append(('全日制',evaluate(leaf('study_mode','eq','full_time'),p),['study_mode'],'本轮选拔面向全日制学术学位硕士。','全日制学术学位硕士'))
        base.append(('外语条件',evaluate(leaf('english_eligible','eq',True),p),['english_eligible'],'核对原文各类外语证明、分数和成绩有效期，不能只凭学生简称认定。','外语'))
    if topic=='phd_marx':base.append(('中期考核良好及以上',evaluate(leaf('midterm_result','in',['excellent','good']),p),['midterm_result'],'中期考核结果须为良好及以上。','良好'))
    return base

