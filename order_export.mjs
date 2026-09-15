import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const [input,output]=process.argv.slice(2);
const data=JSON.parse(await fs.readFile(input,'utf8'));
const wb=Workbook.create(); const sheet=wb.worksheets.add('정리결과');
// Source cells stay literal text, including zero-prefixed identifiers.
const literal=v=>typeof v==='string' && /^[\s]*[=+@-]/.test(v)?"'"+v:v;
const headers=['원본 행','가져올 당시 점검',...data.headers,'정리 수량'];
const matrix=data.records.map(r=>[r.row,r.issues.join(' / ')||'점검 항목 없음',...r.values.map(literal),r.quantity]);
const n=matrix.length,w=headers.length,last=n+7;
sheet.getRange('A2').values=[['주문지 정리 결과']];
sheet.getRange('A3').values=[['가져온 행 수']]; sheet.getRange('B3').values=[[n]];
sheet.getRange('A4').values=[['점검 대상 행']]; sheet.getRange('B4').values=[[data.flagged_rows]];
sheet.getRange('D3').values=[['유효 수량 합계']];
let letters='',col=w; while(col){col--;letters=String.fromCharCode(65+col%26)+letters;col=Math.floor(col/26);}
sheet.getRange('E3').formulas=[[`=SUM(${letters}8:${letters}${last})`]];
sheet.getRange('D4').values=[['중복 의심 포함 / 잘못된 수량 제외']];
sheet.getRange('A5').values=[[data.source.includes('합성')?data.source:'원본을 보존한 정리 사본. 점검 결과는 가져온 시점 기준입니다.']];
sheet.getRangeByIndexes(6,0,1,w).values=[headers];
sheet.getRangeByIndexes(7,2,n,data.headers.length).setNumberFormat('@');
sheet.getRangeByIndexes(7,0,n,w).values=matrix;
const area=sheet.getRangeByIndexes(0,0,last,w);
area.format.font={name:'Arial',size:10,color:'#172A40'}; area.format.rowHeight=24;
area.format.columnWidth=20; area.format.verticalAlignment='center';
sheet.getRange('A2').format.font={name:'Arial',size:15,bold:true};
sheet.getRangeByIndexes(6,0,1,w).format={fill:'#233D59',font:{color:'#FFFFFF',bold:true},rowHeight:30};
sheet.getRangeByIndexes(6,0,1,w).format.horizontalAlignment='center';
sheet.getRangeByIndexes(7,2,n,data.headers.length).setNumberFormat('@');
sheet.getRangeByIndexes(7,w-1,n,1).setNumberFormat('#,##0');
// Explicit zero masks also preserve display in renderers that coerce numeric text.
for(let i=0;i<n;i++) for(let j=0;j<data.headers.length;j++) {
  const v=data.records[i].values[j];
  if(/^0\d+$/.test(v) && v.length<=20) sheet.getCell(i+7,j+2).setNumberFormat('0'.repeat(v.length));
}
sheet.getRange('A1:A'+last).format.columnWidth=19;
sheet.getRange('B1:B'+last).format.columnWidth=48;
sheet.getRange('D1:D'+last).format.columnWidth=42;
sheet.getRangeByIndexes(7,0,n,w).format.wrapText=true;
sheet.getRangeByIndexes(7,0,n,w).format.autofitRows();
sheet.showGridLines=false; sheet.freezePanes.freezeRows(7);
sheet.tables.add(`A7:${letters}${last}`,true,'Orders');
sheet.getRangeByIndexes(7,0,n,w).format.rowHeight=28;
wb.recalculate();
const sum=sheet.getRange('E3').values[0][0];
if(sum!==data.quantity_sum) throw new Error('Quantity reconciliation failed');
const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:10},maxChars:1500});
await fs.writeFile(path.join(path.dirname(output),'verification.json'),JSON.stringify({rows:n,flagged:data.flagged_rows,sum,scan:scan.ndjson}));
if(process.argv.includes('--preview')) {
  const preview=await wb.render({sheetName:'정리결과',range:`A1:${letters}${Math.min(last,15)}`,scale:1,format:'png'});
  await fs.writeFile(path.join(path.dirname(output),'preview.png'),new Uint8Array(await preview.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb); await xlsx.save(output);
console.log(JSON.stringify({rows:n,flagged:data.flagged_rows,quantity:sum}));
