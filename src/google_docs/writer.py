"""Durable outbox, revision-guarded daily sections, idempotent retries."""
import hashlib
import json
import os
from pathlib import Path
from src.utils.io import read_json,write_json

STAGES=[('0730','隔夜确认'),('0830','盘前终审'),('1135','午盘确认'),('1600','收盘扫描'),('2130','晚间二筛')]

def marker(day,stage): return f'[MANSON:{day}:{stage}:PENDING]'
def completed(day,stage): return f'[MANSON:{day}:{stage}:COMPLETE]'
def skeleton(day):
    text=f'\n{day} A股智能分析\n[MANSON:{day}:DAY]\n'
    for stage,label in STAGES:
        text+=f'\n{stage[:2]}:{stage[2:]} {label}\n{marker(day,stage)}\n'
    return text

def all_text(value):
    if isinstance(value,dict):
        return ''.join(v if k=='content' and isinstance(v,str) else all_text(v) for k,v in value.items())
    if isinstance(value,list):return ''.join(all_text(v) for v in value)
    return ''

class DocsOutbox:
    def __init__(self,root,session=None,doc_id=None):
        self.path=Path(root)/'data/pending'
        self.path.mkdir(parents=True,exist_ok=True)
        self.session=session
        self.doc_id=doc_id or os.getenv('GOOGLE_DOC_ID')
    def enqueue(self,day,stage,text):
        p=self.path/f'{day}-{stage}.json'
        old=read_json(p)
        if old and old.get('status')=='SENT': return
        write_json(p,{'date':str(day),'stage':stage,'text':text,'status':'PENDING','attempts':old.get('attempts',0) if old else 0})
    def connect(self):
        if self.session:return True
        credential=os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
        if not self.doc_id or not credential:return False
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import AuthorizedSession
        c=Credentials.from_service_account_info(json.loads(credential),scopes=['https://www.googleapis.com/auth/documents'])
        self.session=AuthorizedSession(c)
        return True
    def get(self):
        r=self.session.get(f'https://docs.googleapis.com/v1/documents/{self.doc_id}',timeout=25)
        r.raise_for_status();return r.json()
    def batch(self,requests,revision):
        r=self.session.post(f'https://docs.googleapis.com/v1/documents/{self.doc_id}:batchUpdate',json={'requests':requests,'writeControl':{'requiredRevisionId':revision}},timeout=25)
        r.raise_for_status()
    def send(self,item):
        doc=self.get();text=all_text(doc)
        day,stage=item['date'],item['stage']
        if completed(day,stage) in text:return 'ALREADY_SENT'
        if f'[MANSON:{day}:DAY]' not in text:
            body=skeleton(day)
            end=doc.get('body',{}).get('content',[{}])[-1].get('endIndex',2)-1
            requests=[{'insertText':{'endOfSegmentLocation':{},'text':body}}]
            offset=end
            for line in body.splitlines(keepends=True):
                if line.strip() and not line.startswith('[MANSON:'):
                    requests.append({'updateParagraphStyle':{'range':{'startIndex':offset,'endIndex':offset+len(line.encode('utf-16-le'))//2},'paragraphStyle':{'namedStyleType':'HEADING_1' if 'A股智能分析' in line else 'HEADING_2'},'fields':'namedStyleType'}})
                offset+=len(line.encode('utf-16-le'))//2
            self.batch(requests,doc['revisionId'])
            doc=self.get();text=all_text(doc)
        if marker(day,stage) not in text:
            raise ValueError('stage placeholder removed by editor; manual recovery required')
        self.batch([{'replaceAllText':{'containsText':{'text':marker(day,stage),'matchCase':True},'replaceText':item['text']+'\n'+completed(day,stage)}}],doc['revisionId'])
        if completed(day,stage) not in all_text(self.get()):
            raise ValueError('write not verified')
        return 'SENT'
    def flush(self):
        try:
            if not self.connect():return {'status':'NOT_CONFIGURED','pending':len(list(self.path.glob('*.json')))}
        except Exception as exc:
            return {'status':'AUTH_FAILED','error':type(exc).__name__}
        sent,failed=0,0
        for path in sorted(self.path.glob('*.json')):
            item=read_json(path)
            if item['status']=='SENT':continue
            try:
                self.send(item)
                item.update(status='SENT',error=None);sent+=1
            except Exception as exc:
                item['error']=type(exc).__name__;failed+=1
            item['attempts']+=1;write_json(path,item)
        return {'status':'PENDING' if failed else 'SYNCED','sent':sent,'failed':failed}
