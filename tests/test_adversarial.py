import numpy as np
import pytest
from spmo_margin.backtest import Account, simulate
from spmo_margin.bootstrap import simulate_paths

@pytest.mark.parametrize('returns', [[-.4,0], [.05,-.4,0], [0,-.9,.5]])
@pytest.mark.parametrize('schedule', ['daily','monthly','never','band'])
@pytest.mark.parametrize('contribution', [0.,1000.])
def test_ruin_metrics_match_to_one_billionth(returns,schedule,contribution):
    r=np.array(returns,dtype=float)
    a=simulate(r,np.full(len(r),.0363),Account(leverage=3.,rebalance=schedule,monthly_contribution=contribution))
    b=simulate_paths(r[None,:],3.,.0363,rebalance=schedule,monthly_contribution=contribution)
    assert a['stats']['wiped_out']
    for key in ['cagr','max_drawdown']:
        assert a['stats'][key]==pytest.approx(-1.,abs=1e-9)
        assert a['stats'][key]==pytest.approx(b[key][0],rel=1e-9,abs=1e-9)
    assert a['equity'][-1]==pytest.approx(b['terminal_equity'][0],abs=1e-9)

@pytest.mark.parametrize('leverage',[.5,1.,1.475,3.])
@pytest.mark.parametrize('schedule',['daily','monthly','never','band'])
@pytest.mark.parametrize('contribution',[0.,1000.])
def test_joint_rate_paths_match_scalar(leverage,schedule,contribution):
    rng=np.random.default_rng(73)
    returns=rng.normal(.0003,.02,(3,400))
    rates=rng.uniform(0.,.12,(3,400))
    vector=simulate_paths(returns,leverage,rates,rebalance=schedule,monthly_contribution=contribution)
    for i in range(3):
        scalar=simulate(returns[i],rates[i],Account(leverage=leverage,rebalance=schedule,monthly_contribution=contribution))
        for key in ['cagr','max_drawdown','interest_paid','margin_calls','rebalances']:
            assert vector[key][i]==pytest.approx(scalar['stats'][key],rel=1e-9,abs=1e-9)
        assert vector['terminal_equity'][i]==pytest.approx(scalar['equity'][-1],rel=1e-9,abs=1e-9)

def test_common_rate_path_and_shape_validation():
    r=np.full((2,40),.0001);rates=np.linspace(0,.06,40)
    a=simulate_paths(r,1.5,rates);b=simulate_paths(r,1.5,np.tile(rates,(2,1)))
    np.testing.assert_allclose(a['terminal_equity'],b['terminal_equity'],rtol=1e-9,atol=1e-9)
    with pytest.raises(ValueError):simulate_paths(r,1.5,np.ones(39))

def test_constrained_growth_does_not_maximise_leverage():
    import pandas as pd
    from spmo_margin.optimal import constrained_growth_optimal
    t=pd.DataFrame({'median_cagr':[.1,.15,.11],'prob_deep_drawdown':[.1,.4,.8]},index=[1.,2.,3.])
    assert constrained_growth_optimal(t,1.)==2.
    assert constrained_growth_optimal(t,.25)==pytest.approx(1.5,abs=1e-9)
    assert np.isnan(constrained_growth_optimal(t,.05))
