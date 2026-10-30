"""Read the supplied archive without executing document instructions."""
from pathlib import Path
import sys,json,zipfile,hashlib,uuid,re,argparse
from io import BytesIO
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT,DATA
from docx import Document
from pypdf import PdfReader

EXCLUDED={2,3,10,11,14,16,17,27,28,46,47,53,54,55}

def docx_text(blob):
    d=Document(BytesIO(blob))
    blocks=[]
    for child in d.element.body:
        if child.tag.endswith('}p'):
            text=''.join(child.itertext())
            # python-docx's XML text may include duplicates; select text nodes directly.
            text=''.join(child.xpath('.//w:t/text()'))
            if text.strip():blocks.append(text.strip())
        elif child.tag.endswith('}tbl'):
            rows=[]
            for row in child.xpath('./w:tr'):
                cells=[''.join(c.xpath('.//w:t/text()')).strip() for c in row.xpath('./w:tc')]
                rows.append(' | '.join(cells))
            blocks.extend(rows)
    return '\n'.join(blocks)

def main():
    parser=argparse.ArgumentParser(description='重解析项目已有原件，或导入本项目最初提供的同结构压缩包。其他数据集须另行制定范围映射。')
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    if args.archive:
        entries=[]
        with zipfile.ZipFile(args.archive) as z:
            if sum(i.file_size for i in z.infolist())>=100_000_000:raise ValueError('Archive is too large')
            for index,info in enumerate(z.infolist()):
                if info.is_dir():continue
                name=info.filename
                if not info.flag_bits&0x800:
                    try:name=name.encode('cp437').decode('gb18030')
                    except UnicodeError:pass
                entries.append((f'p{index:03}',name,z.read(info),index not in EXCLUDED))
    else:
        source=DATA/'manifests'/'policies.json'
        if not source.exists():raise SystemExit('没有已有清单，请显式传入 --archive 原始压缩包路径。')
        previous=json.loads(source.read_text(encoding='utf-8'))
        entries=[]
        for p in previous['files']:
            path=(ROOT/p['raw_file']).resolve()
            if not path.is_relative_to((DATA/'raw').resolve()):raise ValueError('Raw path outside data/raw')
            blob=path.read_bytes()
            if hashlib.sha256(blob).hexdigest()!=p['sha256']:raise ValueError('Raw file hash changed: '+p['key'])
            entries.append((p['key'],p['archive_name'],blob,p['in_scope']))
    rows=[]
    for key,name,blob,in_scope in entries:
            suffix=Path(name).suffix.lower()
            if suffix not in {'.doc','.docx','.pdf'}:raise ValueError('Unsupported original: '+name)
            raw=DATA/'raw'/f'{key}{suffix}'
            if raw.exists() and raw.read_bytes()!=blob:raise ValueError('Refusing to overwrite different original: '+key)
            raw.write_bytes(blob)
            text='';status='parsed'
            if suffix=='.docx':text=docx_text(blob)
            elif suffix=='.pdf':text='\n\n'.join(f'第{i+1}页\n{p.extract_text() or ""}' for i,p in enumerate(PdfReader(BytesIO(blob)).pages))
            elif suffix=='.doc':
                converted=DATA/'converted'/f'{key}.docx'
                if converted.exists():text=docx_text(converted.read_bytes())
                else:status='conversion_pending'
            title=next((t.strip() for t in text.splitlines() if t.strip()),Path(name).stem)
            row={'key':key,'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'campus-policy/'+key)),'archive_name':name,'title':title,'extension':suffix,'raw_file':str(raw.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(blob).hexdigest(),'text':text,'parse_status':status,'in_scope':in_scope,'review_status':'provided_copy_unreviewed','source_url':None,'body_urls':re.findall(r'https?://[^\s）)]+',text)}
            (DATA/'normalized'/f'{key}.txt').write_text(text,encoding='utf-8')
            rows.append(row)
    manifest={'release_id':'provided-copies-20261030-v1','source':'用户提供的政策副本，待业务复核','files':rows,'files_count':len(rows),'parsed_count':sum(x['parse_status']=='parsed' for x in rows)}
    (DATA/'manifests'/'policies.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False))

if __name__=='__main__':main()

