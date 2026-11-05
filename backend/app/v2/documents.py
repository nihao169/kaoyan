"""Bounded extraction for private materials; source view is not fabricated."""
import io
import zipfile
from ..errors import fail


def extract(content, suffix):
    try:
        if suffix in ('txt', 'md'):
            return content.decode('utf-8-sig')
        if suffix == 'pdf':
            import pymupdf
            with pymupdf.open(stream=content, filetype='pdf') as pdf:
                if len(pdf)>500:
                    fail(422,'TOO_MANY_PAGES','资料最多500页')
                if pdf.needs_pass:
                    fail(422,'PASSWORD_REQUIRED','请先移除文档密码')
                return '\n\n'.join(f'[第 {index+1} 页]\n{page.get_text()}' for index,page in enumerate(pdf))
        if suffix == 'docx':
            from docx import Document
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(item.file_size for item in archive.infolist())>50*1024*1024:
                    fail(422,'EXPANDED_FILE_TOO_LARGE','文档解压后过大')
            doc=Document(io.BytesIO(content))
            return '\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(' | '.join(c.text for c in row.cells) for table in doc.tables for row in table.rows)
        fail(422,'UNSUPPORTED_FILE','支持 PDF、DOCX、TXT 和 Markdown')
    except (ValueError,UnicodeError,KeyError,OSError,zipfile.BadZipFile):
        fail(422,'PARSE_FAILED','无法读取资料，请检查格式或先进行 OCR')
