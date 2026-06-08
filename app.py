# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
from config import Config
from database import db
from models import User, Post, Like
import os
import time  # Dùng để tạo tên file duy nhất, tránh trùng lặp
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# ==========================================
# CẤU HÌNH UPLOAD FILE
# ==========================================
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Tự động tạo thư mục static/uploads nếu chưa tồn tại
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Kiểm tra đuôi file có hợp lệ hay không"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

with app.app_context():
    db.create_all()

# ==========================================
# MIDDLEWARE BẢO MẬT (PHÂN QUYỀN)
# ==========================================
def login_required(f):
    """Bắt buộc người dùng (cả Admin và Độc giả) phải đăng nhập"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Bạn cần đăng nhập để thực hiện hành động này!', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Chỉ cho phép tài khoản đầu tiên (ID = 1) làm Admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session['user_id'] != 1:
            flash('Chỉ Admin mới có quyền truy cập trang này!', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# ROUTES: TRANG CHỦ & BÀI VIẾT
# ==========================================
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '')
    
    query = Post.query
    if search_query:
        query = query.filter(Post.title.contains(search_query) | Post.content.contains(search_query))
        
    posts = query.order_by(Post.created_at.desc()).paginate(page=page, per_page=5)
    return render_template('index.html', posts=posts, search_query=search_query)

@app.route('/post/<int:post_id>')
def read_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # --- ĐÃ SỬA: KIỂM TRA LƯỢT XEM BẰNG SESSION ---
    # Lấy danh sách các bài đã xem từ session (nếu chưa có thì tạo list rỗng)
    viewed_posts = session.get('viewed_posts', [])
    
    # Nếu ID bài viết chưa nằm trong danh sách đã xem -> Tính là 1 lượt xem mới
    if post_id not in viewed_posts:
        post.views += 1
        db.session.commit()
        
        # Thêm bài viết này vào danh sách đã xem và lưu lại vào session
        viewed_posts.append(post_id)
        session['viewed_posts'] = viewed_posts
    # ---------------------------------------------
    
    return render_template('post.html', post=post)

@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required 
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    current_user = session['user_id']
    
    # Truy vấn xem User này đã từng thả tim bài này chưa
    existing_like = Like.query.filter_by(user_id=current_user, post_id=post_id).first()
    
    if existing_like:
        # Nếu đã có data (Đã tim) -> Bấm lần nữa sẽ là Bỏ tim (Xóa khỏi DB)
        db.session.delete(existing_like)
    else:
        # Nếu chưa có data -> Tạo lượt tim mới
        new_like = Like(user_id=current_user, post_id=post_id)
        db.session.add(new_like)
        
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

# ==========================================
# ROUTES: TÀI KHOẢN (ĐĂNG KÝ / ĐĂNG NHẬP)
# ==========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Tên người dùng đã tồn tại.', 'danger')
            return redirect(url_for('register'))
            
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Đăng ký thành công! Vui lòng đăng nhập.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            session['user_id'] = user.id
            flash('Đăng nhập thành công!', 'success')
            # Nếu là Admin (id=1) vào thẳng Dashboard, Độc giả (id>1) về Trang chủ
            if user.id == 1:
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('index'))
        flash('Sai tài khoản hoặc mật khẩu.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Đã đăng xuất.', 'info')
    return redirect(url_for('index'))

# ==========================================
# ROUTES: QUẢN TRỊ (CHỈ ADMIN MỚI VÀO ĐƯỢC)
# ==========================================
@app.route('/dashboard')
@admin_required
def dashboard():
    total_posts = Post.query.count()
    total_views = db.session.query(db.func.sum(Post.views)).scalar() or 0
    total_users = User.query.count()
    user_posts = Post.query.filter_by(author_id=session['user_id']).order_by(Post.created_at.desc()).all()
    
    return render_template('dashboard.html', 
                           posts=user_posts, 
                           total_posts=total_posts, 
                           total_views=total_views,
                           total_users=total_users)

@app.route('/post/new', methods=['GET', 'POST'])
@admin_required
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        
        # 1. Đặt ảnh bìa mặc định ban đầu
        image_filename = 'default_cover.jpg'
        
        # 2. Kiểm tra xem người dùng có truyền file lên không
        if 'image' in request.files:
            file = request.files['image']
            
            # Nếu người dùng thực sự có chọn 1 file để upload
            if file and file.filename != '':
                if allowed_file(file.filename):
                    # Xóa ký tự đặc biệt khỏi tên file để bảo mật
                    filename = secure_filename(file.filename)
                    # Thêm timestamp vào đầu tên file để không bao giờ bị trùng (VD: 17182921_co_co.jpg)
                    image_filename = f"{int(time.time())}_{filename}"
                    
                    # Lưu file vật lý vào thư mục static/uploads/
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                else:
                    flash('Định dạng file không hợp lệ! Chỉ chấp nhận png, jpg, jpeg, gif.', 'danger')
                    return redirect(request.url)
        
        # 3. Lưu thông tin bài viết vào DB
        new_post = Post(title=title, content=content, image=image_filename, author_id=session['user_id'])
        db.session.add(new_post)
        db.session.commit()
        flash('Đã tạo bài viết mới thành công!', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('create_post.html')

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if request.method == 'POST':
        post.title = request.form['title']
        post.content = request.form['content']
        post.image = request.form.get('image', post.image)
        db.session.commit()
        flash('Đã cập nhật bài viết!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_post.html', post=post)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@admin_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('Đã xóa bài viết.', 'success')
    return redirect(url_for('dashboard'))

# LUÔN LUÔN ĐỂ ĐOẠN NÀY Ở DƯỚI CÙNG CỦA FILE
if __name__ == '__main__':
    app.run(debug=True)