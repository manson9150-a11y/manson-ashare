"""Subprocess entry point; stdout is structured data, never SDK log text."""
import contextlib
import io
import json
import sys


def main():
    request = json.load(sys.stdin)
    result = {'rows': []}
    with contextlib.redirect_stdout(io.StringIO()):
        import baostock as bs
        login = bs.login()
        if login.error_code != '0':
            result['error'] = 'LOGIN_FAILED'
        else:
            try:
                if request['operation'] == 'industry':
                    query = bs.query_stock_industry()
                else:
                    query = bs.query_history_k_data_plus(request['code'],
                        'date,code,open,high,low,close,volume,amount,adjustflag',
                        start_date=request['start'], end_date=request['end'], frequency='d', adjustflag='3')
                while query.error_code == '0' and query.next():
                    result['rows'].append(dict(zip(query.fields, query.get_row_data())))
                if query.error_code != '0':
                    result = {'error': 'QUERY_FAILED', 'rows': []}
            finally:
                bs.logout()
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
