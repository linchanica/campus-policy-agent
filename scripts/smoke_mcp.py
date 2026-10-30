import asyncio,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

async def smoke():
    params=StdioServerParameters(command=str(ROOT/'.venv'/'Scripts'/'python.exe'),args=['-m','app.mcp_server'],cwd=str(ROOT),env={'DISABLE_LOCAL_LLM':'1','PYTHONIOENCODING':'utf-8'})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize();listing=await session.list_tools()
            names=[t.name for t in listing.tools]
            assert set(names)=={'search_policy','get_policy_evidence','check_eligibility','get_materials_and_steps','prepare_handoff'}
            result=await session.call_tool('search_policy',{'query':'雷军本科生奖学金申请条件','topic':'lei_undergrad'})
            assert not result.is_error
            content='\n'.join(getattr(x,'text','') for x in result.content)
            assert 'source_id' in content
            def body(result):
                assert not result.is_error
                return json.loads('\n'.join(getattr(x,'text','') for x in result.content))
            found=body(result)
            source=found['sources'][0]
            evidence=body(await session.call_tool('get_policy_evidence',{'source_id':source['source_id']}))
            assert evidence['text']==source['text']
            eligibility=body(await session.call_tool('check_eligibility',{'topic':'lei_undergrad','profile':{'college':'SAI','program_level':'undergraduate'}}))
            assert eligibility['conditions'] and eligibility['business_review_required']
            materials=body(await session.call_tool('get_materials_and_steps',{'topic':'lei_undergrad'}))
            assert materials['materials_complete'] is False
            handoff=body(await session.call_tool('prepare_handoff',{'question':'虚构测试事项','unresolved_items':['材料版本需确认']}))
            assert handoff['submitted'] is False and handoff['state']=='draft'
            invalid=await session.call_tool('check_eligibility',{'topic':'lei_undergrad','profile':{'academic_rank_pct':101}})
            assert body(invalid)['error']=='INVALID_PROFILE'
            unknown=body(await session.call_tool('get_policy_evidence',{'source_id':'not-a-real-source'}))
            assert unknown['error']=='SOURCE_NOT_FOUND'
            report={'status':'passed','transport':'stdio','tools':names,'all_five_tools_called':True,'invalid_profile_rejected':True,'unknown_source_explicit':True,'search_returns_source_ids':True,'workbuddy_client_connected':False}
            (ROOT/'work'/'mcp_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(asyncio.wait_for(smoke(),timeout=50))
