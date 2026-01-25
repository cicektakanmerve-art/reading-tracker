from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from models import db, ReadingMaterial, Tag, Status

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reading_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def init_default_statuses():
    """Create default statuses if none exist."""
    if Status.query.count() == 0:
        defaults = [
            ('to_read', 'To Read', 'blue', 1),
            ('reading', 'Reading', 'orange', 2),
            ('completed', 'Completed', 'green', 3),
            ('on_hold', 'On Hold', 'pink', 4),
            ('dropped', 'Dropped', 'gray', 5),
        ]
        for name, display, color, pos in defaults:
            db.session.add(Status(name=name, display_name=display, color=color, position=pos))
        db.session.commit()

with app.app_context():
    db.create_all()
    init_default_statuses()


@app.route('/')
def index():
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    tag_filter = request.args.get('tag', '')

    query = ReadingMaterial.query

    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            db.or_(
                ReadingMaterial.title.ilike(search_term),
                ReadingMaterial.notes.ilike(search_term)
            )
        )

    if status_filter:
        query = query.filter(ReadingMaterial.status_id == int(status_filter))

    if tag_filter:
        query = query.join(ReadingMaterial.tags).filter(Tag.name == tag_filter)

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()
    tags = Tag.query.order_by(Tag.name).all()
    statuses = Status.query.order_by(Status.position).all()

    return render_template('index.html',
                         items=items,
                         tags=tags,
                         statuses=statuses,
                         current_status=status_filter,
                         current_tag=tag_filter,
                         search_query=search_query)


@app.route('/api/search')
def api_search():
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    tag_filter = request.args.get('tag', '')

    query = ReadingMaterial.query

    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            db.or_(
                ReadingMaterial.title.ilike(search_term),
                ReadingMaterial.notes.ilike(search_term)
            )
        )

    if status_filter:
        query = query.filter(ReadingMaterial.status_id == int(status_filter))

    if tag_filter:
        query = query.join(ReadingMaterial.tags).filter(Tag.name == tag_filter)

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()

    return jsonify([{
        'id': item.id,
        'title': item.title,
        'link': item.link,
        'status_display': item.status_display,
        'status_color': item.status_color,
        'chapter_current': item.chapter_current,
        'chapter_total': item.chapter_total,
        'progress_percent': item.progress_percent,
        'tags': [tag.name for tag in item.tags]
    } for item in items])


@app.route('/add', methods=['GET', 'POST'])
def add():
    statuses = Status.query.order_by(Status.position).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('add'))

        status_id = request.form.get('status_id')
        item = ReadingMaterial(
            title=title,
            link=request.form.get('link', '').strip() or None,
            status_id=int(status_id) if status_id else None,
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
                         statuses=statuses)


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    item = ReadingMaterial.query.get_or_404(id)
    statuses = Status.query.order_by(Status.position).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('edit', id=id))

        status_id = request.form.get('status_id')
        item.title = title
        item.link = request.form.get('link', '').strip() or None
        item.status_id = int(status_id) if status_id else None
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
                         statuses=statuses)


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


# Status management routes
@app.route('/statuses')
def statuses():
    all_statuses = Status.query.order_by(Status.position).all()
    return render_template('statuses.html', statuses=all_statuses)


@app.route('/statuses/add', methods=['GET', 'POST'])
def add_status():
    if request.method == 'POST':
        name = request.form.get('name', '').strip().lower().replace(' ', '_')
        display_name = request.form.get('display_name', '').strip()
        color = request.form.get('color', 'gray')

        if not name or not display_name:
            flash('Name and display name are required', 'error')
            return redirect(url_for('add_status'))

        if Status.query.filter_by(name=name).first():
            flash('A status with this name already exists', 'error')
            return redirect(url_for('add_status'))

        max_pos = db.session.query(db.func.max(Status.position)).scalar() or 0
        status = Status(name=name, display_name=display_name, color=color, position=max_pos + 1)
        db.session.add(status)
        db.session.commit()
        flash('Status added successfully', 'success')
        return redirect(url_for('statuses'))

    return render_template('status_form.html', status=None)


@app.route('/statuses/edit/<int:id>', methods=['GET', 'POST'])
def edit_status(id):
    status = Status.query.get_or_404(id)

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        color = request.form.get('color', 'gray')

        if not display_name:
            flash('Display name is required', 'error')
            return redirect(url_for('edit_status', id=id))

        status.display_name = display_name
        status.color = color
        db.session.commit()
        flash('Status updated successfully', 'success')
        return redirect(url_for('statuses'))

    return render_template('status_form.html', status=status)


@app.route('/statuses/delete/<int:id>', methods=['POST'])
def delete_status(id):
    status = Status.query.get_or_404(id)

    # Check if any reading materials use this status
    if status.reading_materials.count() > 0:
        flash('Cannot delete status that is in use', 'error')
        return redirect(url_for('statuses'))

    db.session.delete(status)
    db.session.commit()
    flash('Status deleted', 'success')
    return redirect(url_for('statuses'))


if __name__ == '__main__':
    app.run(debug=True)
