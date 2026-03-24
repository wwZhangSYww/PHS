from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from models import db, User, Admin, Notice, FamilyMember, PublicHealthEvent, DiseaseKnowledge, MedicalReport
import re
import os
import json
import time

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///health_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'public_health_secret_key_2026'

# 配置文件上传路径
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'reports')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(app)


def seed_disease_knowledge():
    if db.session.query(DiseaseKnowledge).count() == 0:
        json_path = os.path.join(app.root_path, 'static', 'data', 'illness.json')
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for cat, subs in data.items():
                    for sub, specs in subs.items():
                        if isinstance(specs, list):
                            _create_knowledge_records(cat, sub, specs)
                        elif isinstance(specs, dict):
                            for ssub, sspecs in specs.items():
                                _create_knowledge_records(cat, f"{sub}-{ssub}", sspecs)
            db.session.commit()
        except Exception as e:
            print(f"系统：疾病库初始化失败: {e}")


def _create_knowledge_records(cat, sub, specs):
    for spec in specs:
        if spec == '高血压':
            cause, symptoms, prev = "长期高盐饮食、精神紧张、遗传因素导致的动脉血压持续升高。", "常伴有头晕、头痛、心悸、颈项板紧、疲劳等症状。", "干预指南：限制钠盐摄入，规律进行有氧运动，保持情绪稳定，遵医嘱按时服用降压药。"
        elif spec == '糖尿病':
            cause, symptoms, prev = "胰岛素分泌缺陷或其生物作用受损引起的糖代谢紊乱。", "典型的多饮、多尿、多食和体重减轻（三多一少），常伴视力模糊。", "干预指南：严格控制饮食总热量，合理分配碳水化合物，监测空腹与餐后血糖。"
        elif spec == '肥胖症':
            cause, symptoms, prev = "能量摄入长期超过能量消耗，导致体内脂肪过度蓄积。", "BMI 指数超标，伴有活动后气促、关节酸痛、内分泌失调。", "干预指南：限制高脂高糖饮食，每日坚持30分钟以上中等强度运动，定期体检。"
        elif spec == '新型冠状病毒感染':
            cause, symptoms, prev = "由 SARS-CoV-2 病毒引发的急性呼吸道传染病，主要通过飞沫和密切接触传播。", "发热、干咳、乏力为主要表现，部分患者可能出现味觉或嗅觉丧失。", "干预指南：公共场所佩戴口罩，保持手部卫生，接种疫苗，室内经常通风。"
        else:
            cause = f"关于 {spec} 的致病因子多涉及环境暴露、遗传因素、或特定病原微生物的感染。"
            symptoms = f"在临床诊断中，{spec} 患者通常表现出其特异性的生理指标异常及身体功能性障碍。"
            prev = f"医疗健康指南建议：保持良好的生活方式，避免接触相关诱发源，并进行针对性的定期筛查。"

        if not db.session.query(DiseaseKnowledge).filter_by(name=spec).first():
            dk = DiseaseKnowledge(category=cat, sub_category=sub, name=spec, cause=cause, symptoms=symptoms,
                                  prevention=prev)
            db.session.add(dk)


with app.app_context():
    db.create_all()
    if not db.session.query(Admin).filter_by(account='admin').first():
        super_admin = Admin(account='admin', name='超级管理员', role='super')
        super_admin.set_password('admin123')
        db.session.add(super_admin)
        db.session.commit()
    seed_disease_knowledge()


# 全局权限拦截：如果用户被锁定，拦截一切修改数据的操作
@app.before_request
def enforce_readonly_lock():
    if request.method == 'POST' and 'user_id' in session:
        # 放行只读和安全路由 (退出、测算)
        allowed_routes = ['logout', 'risk_assessment']
        if request.endpoint in allowed_routes:
            return None

        user = db.session.get(User, session['user_id'])
        if user and user.is_locked:
            flash('您的数据已被锁定，无法进行修改。')
            return redirect(request.referrer or url_for('user_dashboard'))


@app.context_processor
def inject_global_data():
    role = session.get('role')
    if role in ['super', 'community', 'medical']:
        admin = db.session.get(Admin, session.get('admin_id'))
        if role == 'super':
            alert_events = db.session.query(PublicHealthEvent).filter(
                (PublicHealthEvent.status == 'escalated') | (PublicHealthEvent.is_severe == True)
            ).filter(PublicHealthEvent.status != 'processed').order_by(PublicHealthEvent.created_at.desc()).all()
            unread_reports = 0
        else:
            if admin:
                managed_uids = [u.id for u in admin.managed_users]
                alert_events = db.session.query(PublicHealthEvent).filter(
                    ((PublicHealthEvent.status == 'escalated') | (PublicHealthEvent.is_severe == True)) &
                    (PublicHealthEvent.status != 'processed') &
                    db.or_(
                        PublicHealthEvent.reporter_id.in_(managed_uids),
                        db.and_(
                            PublicHealthEvent.province == admin.province,
                            PublicHealthEvent.city == admin.city,
                            PublicHealthEvent.community.startswith(admin.community) if admin.community else True
                        )
                    )
                ).order_by(PublicHealthEvent.created_at.desc()).all()

                # 检查次管管辖用户是否有未读报告
                unread_reports = db.session.query(MedicalReport).join(FamilyMember).filter(
                    FamilyMember.user_id.in_(managed_uids),
                    MedicalReport.is_read_by_admin == False,
                    MedicalReport.uploader_role == 'user'
                ).count()
            else:
                alert_events = []
                unread_reports = 0

        all_admin_notices = db.session.query(Notice).filter(Notice.is_hidden == False,
                                                            Notice.target_audience.in_(['all', 'admin'])).order_by(
            Notice.create_time.desc()).all()
        admin_notices = []
        if admin:
            for n in all_admin_notices:
                if role == 'super':
                    admin_notices.append(n)
                else:
                    if (not n.target_province or n.target_province == admin.province) and \
                            (not n.target_city or n.target_city == admin.city) and \
                            (not n.target_community or admin.community.startswith(n.target_community)):
                        admin_notices.append(n)

        return dict(alert_events=alert_events, admin_notices=admin_notices, unread_reports=unread_reports)
    return dict()


def safe_float(val):
    if not val: return None
    try:
        return float(val)
    except:
        return None


def safe_int(val):
    if not val: return None
    try:
        return int(val)
    except:
        return None


def calculate_bmi_info(height_cm, weight_kg):
    if not height_cm or not weight_kg: return None, "数据不足", "normal"
    bmi = round(weight_kg / ((height_cm / 100) ** 2), 1)
    if bmi < 18.5:
        return bmi, "体重过低", "warning"
    elif 18.5 <= bmi < 24.9:
        return bmi, "体重正常", "success"
    elif 25 <= bmi < 29.9:
        return bmi, "超重", "danger"
    else:
        return bmi, "肥胖", "danger"


def evaluate_bp(high, low):
    if high is None or low is None: return None, "未填写", "normal"
    try:
        h, l = int(high), int(low)
    except:
        return None, "数据异常", "normal"
    if h >= 140 or l >= 90:
        return f"{h}/{l}", "血压偏高", "danger"
    elif h < 90 or l < 60:
        return f"{h}/{l}", "血压偏低", "warning"
    else:
        return f"{h}/{l}", "血压正常", "success"


def scan_and_auto_report():
    risky_members = db.session.query(FamilyMember).filter_by(is_public_health_risk=True).all()
    for m in risky_members:
        if not m.disease_info: continue
        diseases = m.disease_info.split('；\n')
        for d in diseases:
            if '传染病' in d or '甲类' in d:
                specific = d.split('-')[-1].strip() if '-' in d else '高危传染病'
                existing = db.session.query(PublicHealthEvent).filter(
                    PublicHealthEvent.reporter_id == m.user_id,
                    PublicHealthEvent.disease_specific == specific,
                    PublicHealthEvent.disease_sub_category.like('%系统自动巡检%')
                ).first()
                if not existing:
                    user = db.session.get(User, m.user_id)
                    content = f"系统自动巡检警报：检测到家庭成员档案（关系：{m.relation}，姓名：{m.name}）存在高危传染病记录：{d}。请立即核实处理。"
                    auto_event = PublicHealthEvent(
                        reporter_id=user.id, disease_category="传染病", disease_sub_category="系统自动巡检抓取",
                        disease_specific=specific, province=m.province or user.province, city=m.city or user.city,
                        community=m.community or user.community,
                        specific_location=m.address or user.address or "系统登记住址",
                        content=content, contact=user.phone, is_severe=True, status='escalated'
                    )
                    db.session.add(auto_event)
    db.session.commit()


@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        account, password, role_type = request.form.get('account'), request.form.get('password'), request.form.get(
            'role_type')
        if role_type == 'admin':
            admin = db.session.query(Admin).filter_by(account=account).first()
            if admin and admin.check_password(password):
                if admin.is_frozen:
                    flash('该管理员账号已被冻结，请联系超级管理员！')
                    return redirect(url_for('login'))
                session['admin_id'], session['role'] = admin.id, admin.role
                scan_and_auto_report()
                return redirect(url_for('super_admin_dashboard' if admin.role == 'super' else 'sub_admin_dashboard'))
            flash('管理员账号或密码错误')
        elif role_type == 'user':
            if not re.match(r'^1[3-9]\d{9}$', account):
                flash('登录账号应为注册时的电话号码！')
                return redirect(url_for('login'))
            user = db.session.query(User).filter_by(phone=account).first()
            if user and user.check_password(password):
                session.pop('login_attempts', None)
                if user.is_frozen:
                    flash('账号已被冻结，无法登录系统！')
                    return redirect(url_for('login'))
                session['user_id'] = user.id
                if not user.is_info_complete: return redirect(url_for('fill_info'))
                return redirect(url_for('user_dashboard'))
            else:
                attempts = session.get('login_attempts', 0) + 1
                session['login_attempts'] = attempts
                if attempts >= 5:
                    flash('密码错误，若忘记密码请联系上级管理员。')
                else:
                    flash('账号或密码错误')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone, password = request.form.get('phone'), request.form.get('password')
        if not re.match(r'^1[3-9]\d{9}$', phone):
            flash('请填写正确的电话号码')
            return redirect(url_for('register'))
        if db.session.query(User).filter_by(phone=phone).first():
            flash('该手机号已注册')
        else:
            new_user = User(phone=phone)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('注册成功，请登录')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/user_dashboard')
def user_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if not user.is_info_complete: return redirect(url_for('fill_info'))
    notices = db.session.query(Notice).filter(Notice.is_hidden == False,
                                              Notice.target_audience.in_(['all', 'user'])).all()
    filtered_notices = []
    for n in notices:
        if (not n.target_province or n.target_province == user.province) and \
                (not n.target_city or n.target_city == user.city) and \
                (not n.target_community or n.target_community == user.community):
            filtered_notices.append(n)
    admin_names = [m.name for m in user.managers]
    admin_name = ", ".join(admin_names) if admin_names else "暂无"
    return render_template('user_index.html', user=user,
                           notices=sorted(filtered_notices, key=lambda x: x.create_time, reverse=True),
                           admin_name=admin_name)


@app.route('/fill_info', methods=['GET', 'POST'])
def fill_info():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        user.name, user.gender = request.form.get('name'), request.form.get('gender')
        user.province, user.city, user.community = request.form.get('province'), request.form.get(
            'city'), request.form.get('community')
        user.address, user.blood_type = request.form.get('address'), request.form.get('blood_type')
        user.height, user.weight = safe_float(request.form.get('height')), safe_float(request.form.get('weight'))
        user.is_info_complete = True
        self_member = FamilyMember(user_id=user.id, name=user.name, relation="本人", gender=user.gender,
                                   phone=user.phone, province=user.province, city=user.city, community=user.community,
                                   address=user.address, height=user.height, weight=user.weight)
        db.session.add(self_member)
        community_admins = db.session.query(Admin).filter_by(role='community', province=user.province,
                                                             city=user.city).all()
        for ca in community_admins:
            if user.community and ca.community and user.community.startswith(ca.community):
                if ca not in user.managers: user.managers.append(ca)
        db.session.commit()
        return redirect(url_for('profile'))
    return render_template('fill_info.html', user=user)


@app.route('/profile')
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    return render_template('profile.html', user=user)


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        old_pwd, new_pwd, confirm_pwd = request.form.get('old_password'), request.form.get(
            'new_password'), request.form.get('confirm_password')
        if not user.check_password(old_pwd):
            flash('原密码输入错误')
        elif new_pwd != confirm_pwd:
            flash('两次输入的新密码不一致')
        else:
            user.set_password(new_pwd)
            db.session.commit()
            flash('密码修改成功，请重新登录')
            return redirect(url_for('logout'))
    return render_template('change_password.html', user=user)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/super_admin_dashboard')
def super_admin_dashboard():
    if session.get('role') != 'super': return redirect(url_for('login'))
    return render_template('admin_super.html')


@app.route('/sub_admin_dashboard')
def sub_admin_dashboard():
    if session.get('role') not in ['community', 'medical']: return redirect(url_for('login'))
    admin = db.session.get(Admin, session['admin_id'])
    search = request.args.get('search', '')
    users = [u for u in admin.managed_users if
             search in u.phone or (u.name and search in u.name)] if search else admin.managed_users
    sub_notices = db.session.query(Notice).filter_by(sender_name=admin.name).order_by(Notice.create_time.desc()).all()
    return render_template('admin_sub.html', admin=admin, users=users, sub_notices=sub_notices)


@app.route('/admin/manage_accounts', methods=['GET'])
def admin_manage_accounts():
    if session.get('role') != 'super': return redirect(url_for('login'))
    user_search = request.args.get('user_search', '')
    if user_search:
        users = db.session.query(User).filter(
            (User.phone.contains(user_search)) | (User.name.contains(user_search))).all()
    else:
        users = db.session.query(User).all()
    admin_search = request.args.get('admin_search', '')
    if admin_search:
        admins = db.session.query(Admin).filter(Admin.role != 'super', (Admin.account.contains(admin_search)) | (
            Admin.name.contains(admin_search))).all()
    else:
        admins = db.session.query(Admin).filter(Admin.role != 'super').all()
    return render_template('admin_manage_accounts.html', users=users, admins=admins)


@app.route('/admin/add_sub_admin', methods=['POST'])
def add_sub_admin():
    if session.get('role') != 'super': return redirect(url_for('login'))
    role_type, account, name, password, phone = request.form.get('role_type'), request.form.get(
        'account'), request.form.get('name'), request.form.get('password'), request.form.get('phone')
    if db.session.query(Admin).filter_by(account=account).first() or db.session.query(Admin).filter_by(
            name=name).first():
        flash('账号或名称已存在，请换一个！')
        return redirect(url_for('admin_manage_accounts'))
    new_admin = Admin(account=account, name=name, role=role_type, phone=phone)
    new_admin.set_password(password)
    new_admin.province, new_admin.city = request.form.get('province'), request.form.get('city')
    if role_type == 'community':
        new_admin.community = request.form.get('community')
    elif role_type == 'medical':
        new_admin.medical_org = request.form.get('medical_org')
    db.session.add(new_admin)
    db.session.flush()
    if role_type == 'community':
        users = db.session.query(User).filter_by(province=new_admin.province, city=new_admin.city).all()
        for u in users:
            if u.community and new_admin.community and u.community.startswith(new_admin.community):
                if new_admin not in u.managers: u.managers.append(new_admin)
    db.session.commit()
    flash('二级管理员添加成功！' + ('(已自动绑定辖区用户)' if role_type == 'community' else ''))
    return redirect(url_for('admin_manage_accounts'))


# --- 核心权限修复：超管具有最高权限判定 ---
@app.route('/admin/batch_action', methods=['POST'])
def admin_batch_action():
    current_role = session.get('role')
    if current_role not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    current_admin = db.session.get(Admin, session['admin_id'])
    action, target_type, ids = request.form.get('action'), request.form.get('target_type'), request.form.getlist('ids')
    if not ids:
        flash('请至少选择一项进行操作！')
        return redirect(request.referrer)

    if target_type == 'user':
        for u in db.session.query(User).filter(User.id.in_(ids)).all():
            if action == 'delete':
                # 超管无视锁定强行删除，次管只能删除未锁定的
                if current_role == 'super' or not u.is_locked:
                    db.session.delete(u)
            elif action == 'freeze':
                # 超管随意冻结，次管不能冻结已被超管冻结的
                if current_role == 'super' or u.frozen_by_role != 'super':
                    u.is_frozen, u.frozen_by_name, u.frozen_by_role = True, current_admin.name, current_role
            elif action == 'unfreeze' and u.is_frozen:
                # 超管随意解冻，次管不能解冻超管冻结的
                if current_role == 'super' or u.frozen_by_role != 'super':
                    u.is_frozen, u.frozen_by_name, u.frozen_by_role = False, None, None
            elif action == 'lock':
                # 超管随意锁定，次管不能锁定已被超管锁定的
                if current_role == 'super' or u.locked_by_role != 'super':
                    u.is_locked, u.locked_by_name, u.locked_by_role = True, current_admin.name, current_role
            elif action == 'unlock' and u.is_locked:
                # 超管随意解锁，次管不能解锁超管锁定的
                if current_role == 'super' or u.locked_by_role != 'super':
                    u.is_locked, u.locked_by_name, u.locked_by_role = False, None, None
    elif target_type == 'admin' and current_role == 'super':
        for a in db.session.query(Admin).filter(Admin.id.in_(ids)).all():
            if action == 'delete':
                db.session.delete(a)
            elif action == 'freeze':
                a.is_frozen, a.frozen_by_name, a.frozen_by_role = True, current_admin.name, current_role
            elif action == 'unfreeze':
                a.is_frozen, a.frozen_by_name, a.frozen_by_role = False, None, None

    db.session.commit()
    flash(f'操作执行完毕。')
    return redirect(request.referrer)


@app.route('/admin/assign_manager', methods=['POST'])
def assign_manager():
    if session.get('role') != 'super': return redirect(url_for('login'))
    user_ids, admin_id = request.form.getlist('ids'), request.form.get('admin_id')
    if not user_ids or not admin_id: return redirect(url_for('admin_manage_accounts'))
    sub_admin = db.session.get(Admin, admin_id)
    for u in db.session.query(User).filter(User.id.in_(user_ids)).all():
        if sub_admin not in u.managers: u.managers.append(sub_admin)
    db.session.commit()
    flash('手动关联分配管理员成功！')
    return redirect(url_for('admin_manage_accounts'))


# --- 健康数据管理：用户端 ---
@app.route('/user_health_data', methods=['GET'])
def user_health_data():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    member_id = request.args.get('member_id')
    selected_member = db.session.get(FamilyMember, member_id) if member_id else (
        user.family_members[0] if user.family_members else None)
    return render_template('user_health_data.html', user=user, selected_member=selected_member)


@app.route('/upload_medical_report', methods=['POST'])
def upload_medical_report():
    if 'user_id' not in session: return redirect(url_for('login'))
    member_id = request.form.get('member_id')
    file = request.files.get('report_file')
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        save_name = f"{int(time.time())}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], save_name))
        new_report = MedicalReport(member_id=member_id, uploader_role='user', file_path=f"uploads/reports/{save_name}")
        db.session.add(new_report)
        db.session.commit()
        flash('检查报告上传成功。')
    return redirect(url_for('user_health_data', member_id=member_id))


# --- 健康风险评估 ---
@app.route('/risk_assessment', methods=['GET', 'POST'])
def risk_assessment():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    assessment_result = None

    if request.method == 'POST':
        member_id = request.form.get('member_id')
        member = db.session.get(FamilyMember, member_id)
        if not member.age or not member.gender or member.blood_pressure_systolic is None or member.blood_pressure_diastolic is None:
            assessment_result = {"status": "error",
                                 "msg": "被分析者的基础医学档案不全（必须包含年龄、性别、收缩压、舒张压），无法运行模型。"}
        else:
            warnings = []
            sys, dia = member.blood_pressure_systolic, member.blood_pressure_diastolic
            if sys >= 140 or dia >= 90:
                warnings.append(
                    f"【心血管风险异常】收缩压/舒张压超出阈值({sys}/{dia} mmHg)。<a href='/disease_info?search=高血压#高血压'>查阅指南</a>")
            elif sys < 90 or dia < 60:
                warnings.append("【低血压风险】血压水平低于生理标准，提示脑供血不足或器官灌注不良隐患。")

            if member.height and member.weight:
                bmi = round(member.weight / ((member.height / 100) ** 2), 1)
                if bmi >= 28:
                    warnings.append(
                        f"【代谢综合征风险】您的BMI指数为 {bmi}，判定为肥胖。<a href='/disease_info?search=肥胖症#肥胖症'>查阅指南</a>")
                elif bmi >= 24:
                    warnings.append(f"【代谢综合征风险】您的BMI指数为 {bmi}，判定为超重。")
                elif bmi < 18.5:
                    warnings.append(f"【营养不良风险】您的BMI指数为 {bmi}，判定为过瘦。")

            if member.disease_info:
                for d in member.disease_info.split('；\n'):
                    spec = d.split('-')[-1].strip() if '-' in d else d
                    warnings.append(
                        f"【既往病史】系统档案显示您患有 [{spec}]。<a href='/disease_info?search={spec}#{spec}'>查阅百科</a>")

            if warnings:
                assessment_result = {"status": "danger", "msg": warnings}
            else:
                assessment_result = {"status": "success", "msg": ["各项核心生理指标(血压/BMI)均处于健康区间。"]}

    return render_template('risk_assessment.html', user=user, result=assessment_result)


# --- 健康数据管理：管理端 ---
@app.route('/admin/health_data_select', methods=['GET'])
def admin_health_data_select():
    if session.get('role') not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    admin = db.session.get(Admin, session['admin_id'])
    search = request.args.get('search', '')

    query = db.session.query(FamilyMember).join(User)

    if session.get('role') != 'super':
        managed_uids = [u.id for u in admin.managed_users]
        query = query.filter(
            db.or_(
                FamilyMember.user_id.in_(managed_uids),
                db.and_(
                    User.province == admin.province,
                    User.city == admin.city,
                    User.community.startswith(admin.community) if admin.community else True
                )
            )
        )

    if search:
        query = query.filter(db.or_(FamilyMember.name.contains(search), User.phone.contains(search)))

    members = query.all()
    return render_template('admin_health_data_select.html', admin=admin, members=members, search=search)


@app.route('/admin/health_data/<int:member_id>', methods=['GET', 'POST'])
def admin_health_data(member_id):
    if session.get('role') not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    member = db.session.get(FamilyMember, member_id)
    if not member:
        flash("档案不存在或已删除")
        return redirect(request.referrer)

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_advice':
            member.admin_advice = request.form.get('admin_advice')
            db.session.commit()
            flash('更新成功！')
        elif action == 'upload_report':
            file = request.files.get('report_file')
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                save_name = f"{int(time.time())}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], save_name))
                db.session.add(
                    MedicalReport(member_id=member.id, uploader_role='admin', file_path=f"uploads/reports/{save_name}",
                                  is_read_by_admin=True))
                db.session.commit()
                flash('更新成功。')
        elif action == 'delete_report':
            report = db.session.get(MedicalReport, request.form.get('report_id'))
            if report:
                db.session.delete(report)
                db.session.commit()
                flash('报告已删除。')

    unread_reports = db.session.query(MedicalReport).filter_by(member_id=member.id, is_read_by_admin=False).all()
    for r in unread_reports:
        r.is_read_by_admin = True
    if unread_reports:
        db.session.commit()

    bmi_val, bmi_msg, bmi_status = calculate_bmi_info(member.height, member.weight)
    bp_val, bp_msg, bp_status = evaluate_bp(member.blood_pressure_systolic, member.blood_pressure_diastolic)
    return render_template('admin_health_data.html', m=member, bmi_val=bmi_val, bmi_msg=bmi_msg, bmi_status=bmi_status,
                           bp_val=bp_val, bp_msg=bp_msg, bp_status=bp_status)


@app.route('/admin/user_detail/<int:user_id>', methods=['GET', 'POST'])
def admin_user_detail(user_id):
    if session.get('role') not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    user = db.session.get(User, user_id)
    if request.method == 'POST':
        if user.is_locked:
            flash('您的数据已被锁定')
            return redirect(url_for('admin_user_detail', user_id=user.id))
        user.name, user.gender = request.form.get('name'), request.form.get('gender')
        user.height, user.weight = safe_float(request.form.get('height')), safe_float(request.form.get('weight'))
        user.blood_type, user.address = request.form.get('blood_type'), request.form.get('address')
        new_pwd = request.form.get('new_password')
        if new_pwd: user.set_password(new_pwd)
        db.session.commit()
        flash('更新成功！')
        return redirect(url_for('admin_user_detail', user_id=user.id))
    return render_template('admin_user_detail.html', user=user)


@app.route('/admin/sub_admin_detail/<int:admin_id>', methods=['GET', 'POST'])
def admin_sub_detail(admin_id):
    if session.get('role') != 'super': return redirect(url_for('login'))
    admin = db.session.get(Admin, admin_id)
    if request.method == 'POST':
        new_account, new_name, admin.phone = request.form.get('account'), request.form.get('name'), request.form.get(
            'phone')
        if db.session.query(Admin).filter(Admin.account == new_account, Admin.id != admin.id).first() or \
                db.session.query(Admin).filter(Admin.name == new_name, Admin.id != admin.id).first():
            flash('账号或名称已存在！')
            return redirect(url_for('admin_sub_detail', admin_id=admin.id))
        admin.account, admin.name = new_account, new_name
        new_province = request.form.get('province')
        if new_province:
            admin.province, admin.city = new_province, request.form.get('city')
            if admin.role == 'community':
                admin.community = request.form.get('community')
            elif admin.role == 'medical':
                admin.medical_org = request.form.get('medical_org')
        new_pwd = request.form.get('new_password')
        if new_pwd: admin.set_password(new_pwd)
        db.session.commit()
        flash('更新成功！')
        return redirect(url_for('admin_sub_detail', admin_id=admin.id))
    return render_template('admin_sub_detail.html', admin=admin)


@app.route('/family_management', methods=['GET', 'POST'])
def family_management():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        action = request.form.get('action', 'add')
        member_id = request.form.get('member_id')
        if action == 'delete':
            member = db.session.get(FamilyMember, member_id)
            if member and member.relation != '本人':
                db.session.delete(member)
                db.session.commit()
                flash('档案已移除。')
            return redirect(url_for('family_management'))

        name, relation, gender = request.form.get('name'), request.form.get('relation'), request.form.get('gender')
        phone, province, city = request.form.get('phone'), request.form.get('province'), request.form.get('city')
        community, address = request.form.get('community'), request.form.get('address')
        age, height, weight = safe_int(request.form.get('age')), safe_float(request.form.get('height')), safe_float(
            request.form.get('weight'))
        bp_high, bp_low = safe_int(request.form.get('bp_high')), safe_int(request.form.get('bp_low'))
        cats, subs, specs = request.form.getlist('disease_category[]'), request.form.getlist(
            'disease_sub_category[]'), request.form.getlist('disease_specific[]')
        disease_list = []
        is_risk = False
        for i in range(len(cats)):
            c, s, sp = cats[i], (subs[i] if i < len(subs) else ''), (specs[i] if i < len(specs) else '')
            if c and s and sp:
                disease_list.append(f"[{c}] {s} - {sp}")
                if c == '传染病' or '甲类' in s: is_risk = True
        disease_info_str = "；\n".join(disease_list) if disease_list else None

        if action == 'add':
            new_member = FamilyMember(user_id=user.id, name=name, relation=relation, gender=gender, phone=phone,
                                      age=age, province=province, city=city, community=community, address=address,
                                      height=height, weight=weight, blood_pressure_systolic=bp_high,
                                      blood_pressure_diastolic=bp_low, disease_info=disease_info_str,
                                      is_public_health_risk=is_risk)
            db.session.add(new_member)
            flash('建立成功！')
        elif action == 'edit':
            member = db.session.get(FamilyMember, member_id)
            if member:
                member.name, member.gender, member.phone, member.age = name, gender, phone, age
                member.province, member.city, member.community, member.address = province, city, community, address
                member.height, member.weight, member.blood_pressure_systolic, member.blood_pressure_diastolic = height, weight, bp_high, bp_low
                member.disease_info, member.is_public_health_risk = disease_info_str, is_risk
                if member.relation != '本人' and relation: member.relation = relation
                flash('修改成功！')

        db.session.commit()
        scan_and_auto_report()
        return redirect(url_for('family_management'))

    members_data = []
    for m in user.family_members:
        bmi_val, bmi_msg, bmi_status = calculate_bmi_info(m.height, m.weight)
        bp_val, bp_msg, bp_status = evaluate_bp(m.blood_pressure_systolic, m.blood_pressure_diastolic)
        members_data.append(
            {'obj': m, 'bmi_val': bmi_val, 'bmi_msg': bmi_msg, 'bmi_status': bmi_status, 'bp_val': bp_val,
             'bp_msg': bp_msg, 'bp_status': bp_status})

    return render_template('family_management.html', user=user, members_data=members_data)


@app.route('/public_health_report', methods=['GET', 'POST'])
def public_health_report():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        category, sub_category, specific = request.form.get('disease_category'), request.form.get(
            'disease_sub_category'), request.form.get('disease_specific')
        province, city, community = request.form.get('province'), request.form.get('city'), request.form.get(
            'community')
        specific_location, content, contact = request.form.get('specific_location'), request.form.get(
            'content'), request.form.get('contact')

        is_severe = False
        if category == '传染病' and ('甲类' in sub_category or specific in ['鼠疫', '霍乱', '新型冠状病毒感染']):
            is_severe = True

        new_event = PublicHealthEvent(
            reporter_id=user.id, disease_category=category, disease_sub_category=sub_category,
            disease_specific=specific,
            province=province, city=city, community=community, specific_location=specific_location,
            content=content, contact=contact, is_severe=is_severe, status='escalated' if is_severe else 'pending'
        )
        db.session.add(new_event)
        db.session.commit()
        flash('已提交。')
        return redirect(url_for('public_health_report'))

    my_reports = db.session.query(PublicHealthEvent).filter_by(reporter_id=user.id).order_by(
        PublicHealthEvent.created_at.desc()).all()
    return render_template('public_health_report.html', user=user, my_reports=my_reports)


@app.route('/admin/event_audit', methods=['GET', 'POST'])
def admin_event_audit():
    role = session.get('role')
    if role not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    admin = db.session.get(Admin, session['admin_id'])

    if request.method == 'POST':
        action, ids = request.form.get('action'), request.form.getlist('ids')
        for ev in db.session.query(PublicHealthEvent).filter(PublicHealthEvent.id.in_(ids)).all():
            if action == 'delete' and not ev.is_locked:
                db.session.delete(ev)
            elif action == 'lock' and role == 'super':
                ev.is_locked = True
            elif action == 'process':
                if (ev.is_severe or ev.status == 'escalated') and role != 'super':
                    continue
                ev.status = 'processed'
            elif action == 'escalate':
                ev.status, ev.is_severe, ev.escalation_note = 'escalated', True, request.form.get('escalation_note',
                                                                                                  '次级管理员主动升级警报')
        db.session.commit()
        flash('事件处理状态已批量更新！')
        return redirect(url_for('admin_event_audit'))

    if role == 'super':
        events = db.session.query(PublicHealthEvent).order_by(PublicHealthEvent.created_at.desc()).all()
    else:
        managed_uids = [u.id for u in admin.managed_users]
        events = db.session.query(PublicHealthEvent).filter(
            db.or_(
                PublicHealthEvent.reporter_id.in_(managed_uids),
                db.and_(
                    PublicHealthEvent.province == admin.province,
                    PublicHealthEvent.city == admin.city,
                    PublicHealthEvent.community.startswith(admin.community) if admin.community else True
                )
            )
        ).order_by(PublicHealthEvent.created_at.desc()).all()

    return render_template('admin_event_audit.html', events=events, admin=admin)


@app.route('/admin/event_response', methods=['GET', 'POST'])
def admin_event_response():
    if session.get('role') != 'super': return redirect(url_for('login'))
    admin = db.session.get(Admin, session['admin_id'])

    if request.method == 'POST':
        content, notify_users = request.form.get('content'), request.form.get('notify_users') == 'yes'
        target_prov = request.form.get('target_province') or None
        target_city = request.form.get('target_city') or None
        target_comm = request.form.get('target_community') or None

        new_notice = Notice(
            title="通知", content=content,
            target_audience='user' if notify_users else 'admin',
            target_province=target_prov, target_city=target_city, target_community=target_comm,
            sender_name=admin.name, sender_role=admin.role, is_pinned=False, is_locked=False
        )
        db.session.add(new_notice)
        db.session.commit()
        flash('紧急靶向通知已成功发送！')
        return redirect(url_for('admin_event_response'))

    red_events = db.session.query(PublicHealthEvent).filter(
        (PublicHealthEvent.status == 'escalated') | (PublicHealthEvent.is_severe == True)).order_by(
        PublicHealthEvent.created_at.desc()).all()
    notices = db.session.query(Notice).order_by(Notice.create_time.desc()).all()
    return render_template('admin_event_response.html', red_events=red_events, notices=notices)


@app.route('/admin/notice_action', methods=['POST'])
def notice_action():
    if session.get('role') not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    notice_id, action = request.form.get('notice_id'), request.form.get('action')
    notice = db.session.get(Notice, notice_id)
    if notice:
        if action == 'delete':
            db.session.delete(notice)
        elif action == 'toggle':
            notice.is_hidden = not notice.is_hidden
        db.session.commit()
        flash('公告状态已更新')
    if session.get('role') == 'super': return redirect(url_for('admin_event_response'))
    return redirect(url_for('sub_admin_dashboard'))


@app.route('/admin/sub_notice_action', methods=['POST'])
def sub_notice_action():
    if session.get('role') not in ['community', 'medical']: return redirect(url_for('login'))
    admin = db.session.get(Admin, session['admin_id'])
    content = request.form.get('content')
    new_notice = Notice(
        title="通知", content=content,
        target_audience='user',
        target_province=admin.province, target_city=admin.city, target_community=admin.community,
        sender_name=admin.name, sender_role=admin.role, is_pinned=False, is_locked=False
    )
    db.session.add(new_notice)
    db.session.commit()
    flash('辖区通知已成功下发至用户端！')
    return redirect(url_for('sub_admin_dashboard'))


@app.route('/disease_info')
def disease_info():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    search_query = request.args.get('search', '')

    if search_query:
        diseases = db.session.query(DiseaseKnowledge).filter(DiseaseKnowledge.name.contains(search_query)).all()
    else:
        diseases = db.session.query(DiseaseKnowledge).all()

    return render_template('disease_info.html', user=user, diseases=diseases, search_query=search_query)


@app.route('/admin/disease_manage', methods=['GET', 'POST'])
def admin_disease_manage():
    if session.get('role') not in ['super', 'community', 'medical']: return redirect(url_for('login'))
    admin = db.session.get(Admin, session['admin_id'])

    if request.method == 'POST':
        action = request.form.get('action')
        disease_id = request.form.get('disease_id')
        disease = db.session.get(DiseaseKnowledge, disease_id)

        if disease and action == 'edit':
            disease.cause = request.form.get('cause')
            disease.symptoms = request.form.get('symptoms')
            disease.prevention = request.form.get('prevention')
            db.session.commit()
            flash('更新成功！')

    search_query = request.args.get('search', '')
    if search_query:
        diseases = db.session.query(DiseaseKnowledge).filter(DiseaseKnowledge.name.contains(search_query)).all()
    else:
        diseases = db.session.query(DiseaseKnowledge).all()

    return render_template('admin_disease_manage.html', admin=admin, diseases=diseases, search_query=search_query)


if __name__ == '__main__':
    app.run(debug=True, port=5000)