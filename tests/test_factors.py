import pytest
import pandas as pd
from src.factors.technical import technical,wilder_atr

def test_ma_returns_distance(bars):
    f=technical(bars)
    assert f['ma5']==178
    assert f['ma10']==175.5
    assert f['ma20']==170.5
    assert f['ma60']==150.5
    for n in [1,3,5,10,20]:assert f[f'return_{n}d']==pytest.approx((180/(180-n)-1)*100)
    assert f['distance_ma20']==pytest.approx((180/170.5-1)*100)
    assert f['bull_alignment']

def test_wilder_seed_and_recursion():
    df=pd.DataFrame({'high':[11.,13.,12.,17.],'low':[9.,10.,11.,12.],'close':[10.,12.,11.5,16.]})
    atr=wilder_atr(df,3)
    assert pd.isna(atr.iloc[1])
    assert atr.iloc[2]==pytest.approx(2)
    assert atr.iloc[3]==pytest.approx((2*2+5.5)/3)

def test_natr_move_atr(bars):
    f=technical(bars)
    assert f['atr']==2
    assert f['natr']==pytest.approx(2/180*100)
    assert f['move_atr']==pytest.approx(abs(180/179-1)*100/(2/180*100))

def test_short_bars_nulls(bars):
    f=technical(bars.head(4))
    assert f['ma5'] is None and f['atr'] is None and f['return_5d'] is None

def test_volume_baseline_excludes_current(bars):
    bars.loc[79,'amount']=300000000
    f=technical(bars)
    assert f['amount_mean_5d']==100000000
    assert f['amount_ratio_5d']==3

def test_missing_amount_not_estimated(bars):
    bars['amount']=None
    assert technical(bars)['amount_ratio_5d'] is None
