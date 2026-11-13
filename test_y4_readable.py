"""Numeric integrity checks for the readable Y4 mapping (no student database)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

@pytest.fixture(scope='module')
def run_mapping(tmp_path_factory):
    node = shutil.which('node')
    tsc = ROOT / 'frontend/node_modules/typescript/bin/tsc'
    if not node or not tsc.exists():
        pytest.skip('Node and frontend dependencies required')
    out = tmp_path_factory.mktemp('readable-ts')
    subprocess.run([node, str(tsc), str(ROOT / 'frontend/src/pages/profile/y4ReadableData.ts'), '--target', 'ES2020', '--module', 'commonjs', '--strict', '--skipLibCheck', '--outDir', str(out)], check=True, capture_output=True)
    def run(source):
        script = 'const assert=require("node:assert/strict");const m=require('+json.dumps(str(out/'y4ReadableData.js'))+');\n'+source
        subprocess.run([node, '-e', script], check=True, capture_output=True, text=True)
    return run

def test_zero_missing_and_nonfinite_stay_distinct(run_mapping):
    run_mapping('''
      for(const v of [null,undefined,'','  ',true,false,Infinity,'abc']) assert.equal(m.finiteNumber(v),null);
      for(const v of [0,'0',' 0 ']) assert.equal(m.finiteNumber(v),0);
      assert.equal(m.formatValue(0),'0');assert.equal(m.formatValue(null),'—');
      assert.equal(m.formatValue(-2),'-2');assert.equal(m.formatValue(110),'110');
    ''')

def test_rank_gaps_unknown_names_and_missing_scores(run_mapping):
    run_mapping('''
      const rows=m.rankItems([{code:'087',value:'音乐能力'},{code:'088',value:'事业型'},{code:'089',value:'自然能力'},{code:'090',value:'音乐能力'},{code:'081',value:0}], 'abilities');
      assert.deepEqual(rows.map(x=>[x.rank,x.label,x.score]),[[1,'音乐能力',0],[3,'自然能力',undefined]]);
      assert.deepEqual(m.rankItems([{code:'079',value:10}], 'abilities'),[]);
      assert.deepEqual(m.rankItems([{code:'110',value:'生活方式'}],'values').map(x=>[x.rank,x.score]),[[1,undefined]]);
    ''')

def test_b3_keeps_hierarchy_zero_and_missing_scores(run_mapping):
    run_mapping('''
      const groups=m.b3Groups({practice_dims:[{group:'深层',name:'联系',score:0}],exec_items:[{stage:'执行',dim:'检查',name:'回看目标',score:null}]});
      assert.equal(groups.length,2);assert.equal(groups[0].rows[0].score,0);
      assert.equal(groups[1].rows[0].score,null);assert.equal(groups[1].rows[0].label,'执行 / 检查 / 回看目标');
      assert.equal(groups[1].rows[0].max,10);assert.deepEqual(m.b3Groups({}),[]);
    ''')

def test_scales_and_norms_use_distinct_fields(run_mapping):
    run_mapping('''
      assert.deepEqual(m.MEASURES.drive.map(x=>x.normCode),['125','126','127']);
      assert.ok(m.MEASURES.executive.every(x=>x.max===100 && x.unit==='%'));
      assert.ok(m.MEASURES.personality.every(x=>x.max===5));
      assert.ok(m.MEASURES.values.every(x=>x.max===undefined));
      assert.equal(m.MEASURES.abilities[2].code,'081');
    ''')


def test_new_b3_uses_new_measures_without_legacy_substitutions(run_mapping):
    run_mapping(''' 
      const modern=m.learningMeasures([{code:'134',value:0},{code:'135',value:8}]);
      assert.deepEqual(modern.motivation.map(x=>x.code),['066','067']);
      assert.deepEqual(modern.strategy.map(x=>x.code),['069','070','134','135']);
      assert.deepEqual(m.learningMeasures([]).strategy.map(x=>x.code),['069','070','071']);
      assert.deepEqual(m.MEASURES.motivation.map(x=>x.normCode),['128','129','130']);
    ''')


def test_sparse_sections_keep_any_saved_subscore_including_zero(run_mapping):
    run_mapping(''' 
      for(const [section,code] of [['heartA2','016'],['heartA2','031'],['heartB4','054'],['heartB4','062'],['cognitive','003'],['physical','049'],['b3','135'],['b6','086']]) {
        assert.equal(m.readableHasData([{code,value:0}],section),true,section+code);
        assert.equal(m.readableHasData([{code,value:''}],section),false,section+code);
      }
      assert.equal(m.readableHasData([{code:'125',value:6.1}],'heartB4'),false);
      assert.equal(m.readableHasData([{code:'110',value:'生活方式'}],'b6'),true);
      assert.equal(m.readableHasData([{code:'015',value:0}],'cognitive'),false);
    ''')
