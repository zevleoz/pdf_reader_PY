"""Durable activity proposals. No plan mutation until atomic mentor acceptance."""
import copy
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, update, select, func
from sqlalchemy.orm import Session
from m1 import plan_store as store, plan_checks, plan_quality


class ActivityProposal(store.Base):
    __tablename__ = 'm1_plan_activity_proposals'
    id = Column(String(32), primary_key=True)
    plan_id = Column(Integer, ForeignKey('m1_plans.id'), nullable=False, index=True)
    source_version_id = Column(Integer, ForeignKey('m1_plan_versions.id'), nullable=False)
    source_rev = Column(Integer, nullable=False)
    activity_id = Column(String(200), nullable=False)
    session_n = Column(Integer, nullable=False)
    candidate = Column(Text, nullable=False)
    checks = Column(Text, nullable=False)
    manifest = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    consumed_at = Column(DateTime)
    accepted_version_id = Column(Integer)


def ensure_table(engine):
    ActivityProposal.__table__.create(engine, checkfirst=True)


def _writer(sess):
    # SQLite production: acquire writer lock before reading, including cancel/create.
    if sess.bind.dialect.name == 'sqlite':
        sess.connection().exec_driver_sql('BEGIN IMMEDIATE')


def _row(row):
    return {key: store._loads(getattr(row, key), {}) if key in ('candidate', 'checks', 'manifest') else
            store._iso(getattr(row, key)) if key in ('created_at', 'consumed_at') else getattr(row, key)
            for key in ('id', 'plan_id', 'source_version_id', 'source_rev', 'activity_id', 'session_n',
                        'candidate', 'checks', 'manifest', 'status', 'created_by', 'created_at',
                        'consumed_at', 'accepted_version_id')}


def _source(sess, plan_id, rev, version_id, activity_id):
    if type(rev) is not int or type(version_id) is not int or not isinstance(activity_id, str) or not 1 <= len(activity_id) <= 200:
        raise ValueError('需要整数rev/source_version_id和活动编号')
    plan = sess.get(store.M1Plan, plan_id)
    if not plan:
        raise store.NotFound('发展计划不存在')
    store._check_rev(plan, rev)
    if plan.status != 'review':
        raise store.StatusError('只可在待批准状态替换活动；已批准计划请先重新打开')
    if plan.current_version_id != version_id:
        raise store.RevConflict(plan.rev)
    version = sess.get(store.M1PlanVersion, version_id)
    if not version or version.plan_id != plan_id or version.part != 'internal':
        raise store.NotFound('内部版不存在')
    doc = store._activity_text_view(store.normalize_doc_shape(store._loads(version.doc, {})))
    matches = [(si, ai) for si, s in enumerate(doc.get('sessions') or [])
               for ai, a in enumerate(s.get('activities') or []) if a.get('id') == activity_id]
    if len(matches) != 1:
        raise store.StatusError('源活动不存在或编号不唯一')
    si, ai = matches[0]
    if doc['sessions'][si]['activities'][ai].get('block_review'):
        raise ValueError('固定Block Review不能单独重新生成')
    return plan, version, doc, si, ai


def source(plan_id, rev, version_id, activity_id):
    with Session(store._engine()) as sess:
        plan, version, doc, si, ai = _source(sess, plan_id, rev, version_id, activity_id)
        return store._plan_row(sess, plan), doc, si, ai


def create(plan_id, rev, version_id, activity_id, candidate, checks, manifest, actor_id=None):
    with Session(store._engine()) as sess:
        _writer(sess)
        plan, version, doc, si, ai = _source(sess, plan_id, rev, version_id, activity_id)
        row = ActivityProposal(id=uuid.uuid4().hex, plan_id=plan_id, source_version_id=version_id,
            source_rev=rev, activity_id=activity_id, session_n=si+1, candidate=store._dumps(candidate),
            checks=store._dumps(checks), manifest=store._dumps(manifest), created_by=actor_id)
        sess.add(row)
        sess.flush()
        result = _row(row)
        sess.commit()
        return result


def get(plan_id, proposal_id):
    with Session(store._engine()) as sess:
        row = sess.get(ActivityProposal, proposal_id)
        if not row or row.plan_id != plan_id:
            raise store.NotFound('活动建议不存在')
        return _row(row)


def cancel(plan_id, proposal_id):
    with Session(store._engine()) as sess:
        _writer(sess)
        row = sess.get(ActivityProposal, proposal_id)
        if not row or row.plan_id != plan_id:
            raise store.NotFound('活动建议不存在')
        if row.status != 'pending':
            raise store.StatusError('活动建议已处理')
        row.status = 'cancelled'
        row.consumed_at = datetime.utcnow()
        sess.flush()
        result = _row(row)
        sess.commit()
        return result


def accept(plan_id, proposal_id, rev, version_id, activity_id, actor_id=None):
    with Session(store._engine()) as sess:
        _writer(sess)
        proposal = sess.get(ActivityProposal, proposal_id)
        if not proposal or proposal.plan_id != plan_id:
            raise store.NotFound('活动建议不存在')
        if proposal.status != 'pending':
            raise store.StatusError('活动建议已处理，不能重复应用')
        if (proposal.source_rev, proposal.source_version_id, proposal.activity_id) != (rev, version_id, activity_id):
            raise store.StatusError('建议与源版本、修订或活动编号不一致')
        plan, current, doc, si, ai = _source(sess, plan_id, rev, version_id, activity_id)
        candidate = store._loads(proposal.candidate, {})
        refs = candidate.get('input_refs')
        allowed = plan_quality.grounding_refs(store._plan_row(sess, plan))
        if candidate.get('source_issue') or not isinstance(refs, list) or not refs or any(
                not isinstance(r, str) or r not in allowed for r in refs):
            raise ValueError('建议的来源/个性化引用无效，请重新提出建议并核对')
        if candidate.get('minutes') != doc['sessions'][si]['activities'][ai].get('minutes'):
            raise ValueError('替换建议必须保留目标活动分钟数，请重新提出建议')
        allowed_wb = store._loads(proposal.manifest, {}).get('wb_candidates', [])
        source = candidate.get('source') or {}
        if source.get('type') == 'world_bank' and source.get('wb_id') not in allowed_wb:
            raise ValueError('建议WB来源不在本次候选中')
        doc = copy.deepcopy(doc)
        candidate['id'] = activity_id
        candidate['block_review'] = False
        doc['sessions'][si]['activities'][ai] = candidate
        public_plan = store._plan_row(sess, plan)
        store.validate_internal_doc(public_plan, doc)
        plan_quality.validate_additions(doc)
        from m1 import plan_collaboration as collab
        activity_section = 'internal.session.%d.activity.%s' % (si + 1, activity_id)
        session_section = 'internal.session.%d' % (si + 1)
        activity_list_section = 'internal.session.%d.activities' % (si + 1)
        collab._require_lease(sess, plan_id, activity_section, actor_id, None,
                              required=False)
        collab._require_lease(sess, plan_id, session_section, actor_id, None,
                              required=False)
        collab._require_lease(sess, plan_id, activity_list_section, actor_id, None,
                              required=False)
        collab._require_no_related_lease(sess, plan_id, activity_section)
        checks = plan_checks.run_checks(public_plan, doc)
        manifest = store._loads(current.manifest, {})
        manifest['activity_proposal'] = proposal_id
        new = store.M1PlanVersion(plan_id=plan_id, part='internal', n=int(sess.scalar(select(func.max(store.M1PlanVersion.n)).where(
                store.M1PlanVersion.plan_id == plan_id, store.M1PlanVersion.part == 'internal')) or 0)+1,
            kind='edit', ai_doc=current.ai_doc, doc=store._dumps(doc), checks=store._dumps(checks),
            manifest=store._dumps(manifest), source_version_id=current.id, created_by=actor_id)
        sess.add(new)
        sess.flush()
        result = sess.execute(update(store.M1Plan).where(store.M1Plan.id == plan_id,
            store.M1Plan.rev == rev, store.M1Plan.current_version_id == version_id,
            store.M1Plan.status == 'review').values(current_version_id=new.id, rev=rev+1,
                updated_at=datetime.utcnow()), execution_options={'synchronize_session': False})
        if result.rowcount != 1:
            raise store.RevConflict(rev)
        proposal.status = 'accepted'
        proposal.consumed_at = datetime.utcnow()
        proposal.accepted_version_id = new.id
        collab.bump_section_in_session(sess, plan_id, activity_section, actor_id)
        collab.bump_section_in_session(sess, plan_id, session_section, actor_id)
        collab.bump_section_in_session(sess, plan_id, activity_list_section, actor_id)
        sess.commit()
        return {'rev': rev+1, 'version_id': new.id, 'checks': checks}
