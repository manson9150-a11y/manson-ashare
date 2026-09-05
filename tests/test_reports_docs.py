from pathlib import Path
import pytest
from src.google_docs.writer import DocsOutbox,skeleton,marker,completed
from src.reports.render import daily_markdown
from src.utils.io import read_json

class Response:
    def __init__(self,data):self.data=data
    def json(self):return self.data
    def raise_for_status(self):pass

class FakeDocs:
    def __init__(self,fail_after_write=False):self.text='Existing human research\n';self.rev=1;self.calls=0;self.fail_after_write=fail_after_write
    def get(self,url,**kwargs):return Response({'revisionId':str(self.rev),'body':{'content':[{'endIndex':len(self.text.encode('utf-16-le'))//2+1,'paragraph':{'elements':[{'textRun':{'content':self.text}}]}}]}})
    def post(self,url,json,**kwargs):
        assert json['writeControl']['requiredRevisionId']==str(self.rev)
        self.calls+=1
        for r in json['requests']:
            if 'insertText' in r:self.text+=r['insertText']['text']
            if 'replaceAllText' in r:
                item=r['replaceAllText'];self.text=self.text.replace(item['containsText']['text'],item['replaceText'])
        self.rev+=1
        if self.fail_after_write and any('replaceAllText' in r for r in json['requests']):
            self.fail_after_write=False;raise ConnectionError('lost response after successful remote write')
        return Response({})

def test_five_daily_headings():
    s=skeleton('2026-09-04')
    for stage in ['0730','0830','1135','1600','2130']:assert marker('2026-09-04',stage) in s
    assert '2026-09-04 A股智能分析' in daily_markdown('2026-09-04',{})

def test_docs_no_auth_durable_queue(tmp_path,monkeypatch):
    monkeypatch.delenv('GOOGLE_DOC_ID',raising=False);monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_JSON',raising=False)
    out=DocsOutbox(tmp_path);out.enqueue('2026-09-04','1600','报告')
    assert out.flush()['status']=='NOT_CONFIGURED'
    assert read_json(tmp_path/'data/pending/2026-09-04-1600.json')['status']=='PENDING'

def test_retry_after_ambiguous_write_no_duplicate(tmp_path):
    session=FakeDocs(fail_after_write=True);out=DocsOutbox(tmp_path,session,'id')
    out.enqueue('2026-09-04','1600','收盘测试报告')
    assert out.flush()['status']=='PENDING'
    assert out.flush()['status']=='SYNCED'
    assert session.text.count('收盘测试报告')==1
    assert session.text.startswith('Existing human research')
    assert session.text.count('2026-09-04 A股智能分析')==1

def test_multiple_stages_one_daily_section(tmp_path):
    s=FakeDocs();out=DocsOutbox(tmp_path,s,'id')
    for stage in ['1600','2130']:
        out.enqueue('2026-09-04',stage,'阶段'+stage);out.flush()
    assert s.text.count('2026-09-04 A股智能分析')==1
    assert '阶段1600' in s.text and '阶段2130' in s.text
    calls=s.calls;out.flush();assert s.calls==calls
