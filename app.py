from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, ReadingMaterial, Tag

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reading_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()


@app.route('/')
def index():
    status_filter = request.args.get('status', '')
    tag_filter = request.args.get('tag', '')

    query = ReadingMaterial.query

    if status_filter:
        query = query.filter(ReadingMaterial.status == status_filter)

    if tag_filter:
        query = query.join(ReadingMaterial.tags).filter(Tag.name == tag_filter)

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()
    tags = Tag.query.order_by(Tag.name).all()

    return render_template('index.html',
                         items=items,
                         tags=tags,
                         status_choices=ReadingMaterial.STATUS_CHOICES,
                         current_status=status_filter,
                         current_tag=tag_filter)


@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('add'))

        item = ReadingMaterial(
            title=title,
            link=request.form.get('link', '').strip() or None,
            status=request.form.get('status', 'to_read'),
            chapter_current=int(request.form.get('chapter_current', 0) or 0),
            chapter_total=int(request.form.get('chapter_total') or 0) or None,
            notes=request.form.get('notes', '').strip() or None
        )

        # Handle tags
        tag_names = request.form.get('tags', '').strip()
        if tag_names:
            for tag_name in tag_names.split(','):
                tag_name = tag_name.strip().lower()
                if tag_name:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.session.add(tag)
                    item.tags.append(tag)

        db.session.add(item)
        db.session.commit()
        flash('Reading material added successfully', 'success')
        return redirect(url_for('index'))

    return render_template('form.html',
                         item=None,
                         status_choices=ReadingMaterial.STATUS_CHOICES)


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    item = ReadingMaterial.query.get_or_404(id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('edit', id=id))

        item.title = title
        item.link = request.form.get('link', '').strip() or None
        item.status = request.form.get('status', 'to_read')
        item.chapter_current = int(request.form.get('chapter_current', 0) or 0)
        item.chapter_total = int(request.form.get('chapter_total') or 0) or None
        item.notes = request.form.get('notes', '').strip() or None

        # Handle tags - clear and re-add
        item.tags.clear()
        tag_names = request.form.get('tags', '').strip()
        if tag_names:
            for tag_name in tag_names.split(','):
                tag_name = tag_name.strip().lower()
                if tag_name:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.session.add(tag)
                    item.tags.append(tag)

        db.session.commit()
        flash('Reading material updated successfully', 'success')
        return redirect(url_for('index'))

    return render_template('form.html',
                         item=item,
                         status_choices=ReadingMaterial.STATUS_CHOICES)


@app.route('/view/<int:id>')
def view(id):
    item = ReadingMaterial.query.get_or_404(id)
    return render_template('view.html', item=item)


@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    item = ReadingMaterial.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Reading material deleted', 'success')
    return redirect(url_for('index'))


@app.route('/update-progress/<int:id>', methods=['POST'])
def update_progress(id):
    item = ReadingMaterial.query.get_or_404(id)
    chapter = request.form.get('chapter_current', type=int)
    if chapter is not None:
        item.chapter_current = chapter
        db.session.commit()
        flash('Progress updated', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
