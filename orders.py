"""Deterministic local order preparation. Never invokes a model or a network API."""
import csv, io, json, re, subprocess, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from decimal import Decimal, InvalidOperation
import office

ALIASES={'id':{'주문번호','주문id','orderid','주문고유번호'},
 'product':{'상품명','제품명','주문상품명','상품','product'},
 'quantity':{'수량','주문수량','상품수량','quantity','qty'}}
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def key(s): return re.sub(r'[\s_\-]+','',str(s)).lower()

def read_rows(path):
    path=Path(path)
    if path.stat().st_size>20*1024*1024: raise ValueError('20MB 이하 파일을 사용하세요.')
    if path.suffix.lower()=='.csv':
        raw=path.read_bytes()
        try: text=raw.decode('utf-8-sig')
        except UnicodeDecodeError: text=raw.decode('cp949')
        rows=list(csv.reader(io.StringIO(text)))
        if len(rows)>10001: raise ValueError('v1은 파일당 10,000개 데이터 행까지 지원합니다.')
        return 'CSV',rows
    if path.suffix.lower()!='.xlsx': raise ValueError('.xlsx 또는 .csv를 사용하세요. 구형 .xls는 Excel에서 .xlsx로 저장하세요.')
    with zipfile.ZipFile(path) as z:
        if sum(x.file_size for x in z.infolist())>60*1024*1024: raise ValueError('압축 해제 크기 제한을 초과했습니다.')
        def xml(name):
            raw=z.read(name)
            if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw: raise ValueError('지원하지 않는 XML 선언입니다.')
            return ET.fromstring(raw)
        if any('vbaProject' in name for name in z.namelist()): raise ValueError('매크로 파일은 지원하지 않습니다.')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(si.itertext()) for si in xml('xl/sharedStrings.xml')]
        styles=[]; formats={}
        if 'xl/styles.xml' in z.namelist():
            style=xml('xl/styles.xml')
            formats={int(n.attrib['numFmtId']):n.attrib['formatCode'] for n in style.findall('s:numFmts/s:numFmt',NS)}
            styles=[int(n.attrib.get('numFmtId',0)) for n in style.findall('s:cellXfs/s:xf',NS)]
        sheets=[]
        for name in z.namelist():
            if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml',name): continue
            rows=[]
            for row in xml(name).findall('s:sheetData/s:row',NS):
                rindex=int(row.attrib.get('r',len(rows)+1))
                if rindex>10001: raise ValueError('v1은 10,000개 데이터 행까지 지원합니다.')
                cells={}
                for cell in row.findall('s:c',NS):
                    if cell.find('s:f',NS) is not None: raise ValueError('수식이 포함되어 있습니다. 원본은 보관하고 값으로 저장한 주문지 사본을 사용하세요.')
                    letters=re.match(r'[A-Z]+',cell.attrib['r']).group(); idx=0
                    for ch in letters: idx=idx*26+ord(ch)-64
                    if idx>80: raise ValueError('80열 이하의 주문 표를 사용하세요.')
                    v=cell.find('s:v',NS); value=v.text if v is not None and v.text is not None else ''
                    typ=cell.attrib.get('t')
                    if typ=='s': value=strings[int(value)]
                    elif typ=='inlineStr': value=''.join(cell.find('s:is',NS).itertext())
                    elif typ=='e': raise ValueError('원본에 Excel 오류 셀이 있습니다.')
                    else:
                        styleindex=int(cell.attrib.get('s',0)); fmt=formats.get(styles[styleindex],'') if styleindex<len(styles) else ''
                        if re.fullmatch('0+',fmt) and value.isdigit(): value=value.zfill(len(fmt))
                    cells[idx-1]=value
                if cells:
                    while len(rows)<rindex-1: rows.append([])
                    rows.append([cells.get(i,'') for i in range(max(cells)+1)])
            if any(any(str(x).strip() for x in row) for row in rows): sheets.append((name.rsplit('/',1)[1],rows))
        if len(sheets)!=1: raise ValueError('v1은 데이터가 있는 시트 1개를 처리합니다. 처리할 표만 별도 사본으로 저장하세요.')
        return sheets[0]

def prepare(rows,source='CSV'):
    if len(rows)<2: raise ValueError('첫 행 제목과 데이터가 필요합니다.')
    width=max(map(len,rows))
    if width>80: raise ValueError('80열 이하의 주문 표를 사용하세요.')
    headers=[str(v).strip() for v in rows[0]]
    if len(headers)!=width or any(not h for h in headers) or len(set(map(key,headers)))!=width:
        raise ValueError('첫 행에 모든 열의 고유한 제목이 필요합니다. 빈 제목·병합 제목·중복 제목을 확인하세요.')
    mapping={}
    for field,aliases in ALIASES.items():
        found=[i for i,h in enumerate(headers) if key(h) in aliases]
        if len(found)!=1: raise ValueError('주문번호·상품명·수량 열을 각각 하나씩 사용하세요. 현재 확인이 필요한 항목: '+field)
        mapping[field]=found[0]
    records=[]; seen={}
    for number,row in enumerate(rows[1:],2):
        values=[str(x) for x in row]+['']*(width-len(row))
        issues=[]; quantity=None
        for field,idx in mapping.items():
            if not values[idx].strip(): issues.append({'id':'주문번호','product':'상품명','quantity':'수량'}[field]+' 누락')
        try:
            amount=Decimal(values[mapping['quantity']].strip().replace(',',''))
            if not amount.is_finite() or amount<=0 or amount!=amount.to_integral_value() or amount>1_000_000_000: raise InvalidOperation
            quantity=int(amount)
        except InvalidOperation: issues.append('수량 확인')
        rowkey=tuple(values)
        if rowkey in seen:
            issues.append('완전 동일 행 의심')
            previous=records[seen[rowkey]]
            if '완전 동일 행 의심' not in previous['issues']: previous['issues'].append('완전 동일 행 의심')
        else: seen[rowkey]=len(records)
        if any(v.lstrip().startswith(('=','+','-','@')) for v in values): issues.append('수식형 문자 보존')
        records.append({'row':number,'values':values,'quantity':quantity,'issues':issues})
    return {'source':source,'headers':headers,'records':records,'row_count':len(records),
      'flagged_rows':sum(bool(r['issues']) for r in records),'quantity_sum':sum(r['quantity'] or 0 for r in records),
      'policy':'가져올 당시 점검. 모든 행 보존, 중복 의심도 합계 포함. 누락·잘못된 수량은 합계 제외. 실제 출고 확정 아님.'}

def verify_export(path,data):
    """Read saved OOXML independently of the workbook authoring engine."""
    with zipfile.ZipFile(path) as z:
        if z.testzip(): raise ValueError('엑셀 압축 무결성 검사 실패')
        root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        strings=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml'))] if 'xl/sharedStrings.xml' in z.namelist() else []
        cells={c.attrib['r']:c for c in root.findall('.//s:c',NS)}
        def value(address):
            c=cells.get(address)
            if c is None: return ''
            v=c.find('s:v',NS); text=v.text if v is not None and v.text else ''
            return strings[int(text)] if c.attrib.get('t')=='s' else text
        def address(col,row):
            letters=''
            while col: col,r=divmod(col-1,26); letters=chr(65+r)+letters
            return letters+str(row)
        for index,record in enumerate(data['records'],8):
            for col,expected in enumerate(record['values'],3):
                addr=address(col,index)
                if value(addr)!=expected or (addr in cells and cells[addr].find('s:f',NS) is not None):
                    raise ValueError('원본 값 보존 검사 실패: '+addr)
            actual=value(address(len(data['headers'])+3,index))
            if actual!=('' if record['quantity'] is None else str(record['quantity'])): raise ValueError('수량 보존 검사 실패')
        if Decimal(value('E3'))!=data['quantity_sum']: raise ValueError('수량 합계 검사 실패')
        if any(c.attrib.get('t')=='e' for c in cells.values()): raise ValueError('출력 Excel 오류 셀 발견')

def process(path):
    path=Path(path).resolve()
    if not path.is_relative_to((office.ROOT/'inbox/baek').resolve()): raise ValueError('백년화편 받은 파일 폴더만 처리합니다.')
    with office.lock():
        source,rows=read_rows(path); data=prepare(rows,source)
        job=office.uid(); folder=office.ROOT/'orders'/job; folder.mkdir(parents=True)
        office.dump(folder/'input.json',data)
        cfg=office.config(); node=cfg.get('spreadsheet_node')
        if not node or not Path(node).is_file(): raise ValueError('엑셀 출력 실행 환경을 찾을 수 없습니다.')
        result=subprocess.run([node,str(office.ROOT/'order_export.mjs'),str(folder/'input.json'),str(folder/'정리결과.xlsx')],
            capture_output=True,text=True,encoding='utf-8',cwd=office.ROOT,timeout=180)
        (folder/'export.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        output=folder/'정리결과.xlsx'
        if result.returncode or not output.exists(): raise RuntimeError('엑셀 생성 실패. 원본은 보존되었습니다. 로컬 orders 폴더의 export.log를 확인하세요.')
        verify_export(output,data)
        receipt={'id':job,'source_sha256':office.digest(path.read_bytes()),'path':output.relative_to(office.ROOT).as_posix(),
          'sha256':office.digest(output.read_bytes()),'rows':data['row_count'],'flagged':data['flagged_rows'],'created':office.now()}
        office.dump(folder/'receipt.json',receipt)
    # Only aggregate counts enter the team ledger; no customer rows or filename.
    tid=office.add('주문지 로컬 정리 완료','고객 행은 로컬 전용 정리기로 처리했습니다.',role='CTO',important=False,project='baek',owner_agent='baek_orders',task_kind='local_orders')
    with office.lock(),office.db() as c:
        office.state(c,tid,'DONE',json.dumps({'rows':data['row_count'],'flagged':data['flagged_rows'],'order_job':job}))
        c.execute('INSERT INTO employee_notes VALUES (?,?,?,?,?)',(office.uid(),'baek_orders',tid,f"주문 {data['row_count']}행을 보존해 정리. 점검 대상 {data['flagged_rows']}행. 고객 자료는 로컬 전용.",office.now()))
    import briefings
    briefings.after_work('baek')
    return receipt

def receipts():
    return [json.loads(p.read_text(encoding='utf-8')) for p in (office.ROOT/'orders').glob('*/receipt.json')]

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('path'); args=parser.parse_args(); office.init()
    print(json.dumps(process(args.path),ensure_ascii=False))
