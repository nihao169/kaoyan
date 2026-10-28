"""Build original, explicitly labelled political teaching examples with native Word tables."""
import ast
from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
module = ast.parse((ROOT / 'backend/app/seed.py').read_text(encoding='utf-8'))
items = ast.literal_eval(next(n.value for n in module.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='DATA' for t in n.targets)))
output = ROOT / 'docs/samples'
output.mkdir(parents=True, exist_ok=True)
for index, item in enumerate(items):
    versions = (1, 2) if index == 0 else (1,)
    for version in versions:
        doc = Document()
        section = doc.sections[0]
        section.top_margin = section.bottom_margin = Cm(2)
        section.left_margin = section.right_margin = Cm(2.2)
        for name in ('Normal', 'Title', 'Heading 1', 'Heading 2'):
            style = doc.styles[name]
            style.font.name = 'Microsoft YaHei'
            style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
            style.font.color.rgb = RGBColor(0,0,0)
            for borders in list(style.element.iter(qn('w:pBdr'))):
                borders.getparent().remove(borders)
        doc.styles['Normal'].font.size = Pt(11)
        doc.styles['Normal'].paragraph_format.space_after = Pt(8)
        doc.add_paragraph(item['topic'] + '教学样例', 'Title')
        doc.add_paragraph(f"{item['module']}  原创演示资料  版本 {version}")
        doc.add_paragraph('用于验证平台的资料解析、引用和学习流程。本文为原创样例，不是正式教材摘录，也不提供最新时政结论。')
        doc.add_heading('概念与适用条件', level=1)
        doc.add_paragraph(item['principle'])
        if version == 2:
            doc.add_paragraph('修订说明：补充适用边界。单个案例不足以支持无条件推广，应核对新材料的主体、时间、环境与证据。')
        doc.add_heading('材料分析方法', level=1)
        doc.add_paragraph(item['method'])
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text='核对项目'
        table.rows[0].cells[1].text='判断方法'
        for a,b in [('概念','先辨清概念含义，避免相似词替代。'),('条件','检查原理适用条件和材料范围。'),('证据','将材料事实与原理逐项对应，不能以表态代替论证。')]:
            row=table.add_row();row.cells[0].text=a;row.cells[1].text=b
        for i,row in enumerate(table.rows):
            for cell in row.cells:
                tcPr=cell._tc.get_or_add_tcPr()
                borders=OxmlElement('w:tcBorders')
                for side in ('top','left','bottom','right'):
                    border=OxmlElement('w:'+side);border.set(qn('w:val'),'single');border.set(qn('w:sz'),'4');border.set(qn('w:color'),'D9D9D9');borders.append(border)
                tcPr.append(borders)
                if i==0:
                    shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EDF2');tcPr.append(shade)
        doc.add_heading('例题与分析线索', level=1)
        doc.add_paragraph(item['essay'])
        doc.add_paragraph('分析线索：先说明原理，再对应材料事实，最后解释联系及结论边界。')
        footer=section.footer.paragraphs[0]
        footer.add_run('知行研学原创样例  第 ')
        field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
        footer.add_run(' 页')
        doc.save(output / f'politics-{index+1:02d}-v{version}.docx')
print('Built 7 original DOCX samples.')
