from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from models import db, ReadingMaterial, Tag, Status, Note

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
    tag_filters = request.args.getlist('tags')  # Multiple tags support

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

    if tag_filters:
        # Filter items that have ALL selected tags
        for tag_name in tag_filters:
            query = query.filter(
                ReadingMaterial.tags.any(Tag.name == tag_name)
            )

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()
    tags = Tag.query.order_by(Tag.name).all()
    statuses = Status.query.order_by(Status.position).all()

    # Group items by status
    grouped_items = []
    status_map = {}
    for status in statuses:
        group = {
            'status': status,
            'entries': []
        }
        grouped_items.append(group)
        status_map[status.id] = group

    # Add a group for items without status
    no_status_group = {
        'status': None,
        'entries': []
    }
    status_map[None] = no_status_group

    for item in items:
        status_map[item.status_id]['entries'].append(item)

    # Add no-status group at the end if it has entries
    if no_status_group['entries']:
        grouped_items.append(no_status_group)

    return render_template('index.html',
                         items=items,
                         grouped_items=grouped_items,
                         tags=tags,
                         statuses=statuses,
                         current_status=status_filter,
                         current_tags=tag_filters,
                         search_query=search_query)


@app.route('/api/search')
def api_search():
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    tag_filters = request.args.getlist('tags')  # Multiple tags support

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

    if tag_filters:
        # Filter items that have ALL selected tags
        for tag_name in tag_filters:
            query = query.filter(
                ReadingMaterial.tags.any(Tag.name == tag_name)
            )

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()
    statuses = Status.query.order_by(Status.position).all()

    # Group items by status
    grouped = {}
    for status in statuses:
        grouped[status.id] = {
            'status_id': status.id,
            'status_name': status.display_name,
            'status_color': status.color,
            'items': []
        }
    grouped[0] = {
        'status_id': 0,
        'status_name': 'No Status',
        'status_color': 'gray',
        'items': []
    }

    for item in items:
        key = item.status_id if item.status_id else 0
        grouped[key]['items'].append({
            'id': item.id,
            'title': item.title,
            'link': item.link,
            'status_display': item.status_display,
            'status_color': item.status_color,
            'status_id': item.status_id,
            'chapter_current': item.chapter_current,
            'chapter_total': item.chapter_total,
            'progress_percent': item.progress_percent,
            'tags': [{'id': tag.id, 'name': tag.name, 'color': tag.color or 'gray'} for tag in item.tags]
        })

    # Return only groups that have items, maintaining order
    result = []
    for status in statuses:
        if grouped[status.id]['items']:
            result.append(grouped[status.id])
    if grouped[0]['items']:
        result.append(grouped[0])

    return jsonify(result)


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
                tag_name = tag_name.strip()
                if tag_name:
                    # Case-insensitive search for existing tag
                    tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
                    if not tag:
                        tag = Tag(name=tag_name, color=Tag.random_color())
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
                tag_name = tag_name.strip()
                if tag_name:
                    # Case-insensitive search for existing tag
                    tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
                    if not tag:
                        tag = Tag(name=tag_name, color=Tag.random_color())
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
    notes = item.note_entries.order_by(Note.created_at.desc()).all()
    statuses = Status.query.order_by(Status.position).all()
    return render_template('view.html', item=item, notes=notes, statuses=statuses)


@app.route('/view/<int:id>/add-note', methods=['POST'])
def add_note(id):
    item = ReadingMaterial.query.get_or_404(id)
    content = request.form.get('content', '').strip()

    if not content:
        flash('Note content is required', 'error')
        return redirect(url_for('view', id=id))

    note = Note(content=content, reading_material_id=item.id)
    db.session.add(note)
    db.session.commit()
    flash('Note added', 'success')
    return redirect(url_for('view', id=id))


@app.route('/note/<int:id>/delete', methods=['POST'])
def delete_note(id):
    note = Note.query.get_or_404(id)
    reading_material_id = note.reading_material_id
    db.session.delete(note)
    db.session.commit()
    flash('Note deleted', 'success')
    return redirect(url_for('view', id=reading_material_id))


@app.route('/note/<int:id>/edit', methods=['POST'])
def edit_note(id):
    note = Note.query.get_or_404(id)
    content = request.form.get('content', '').strip()

    if not content:
        flash('Note content is required', 'error')
    else:
        note.content = content
        db.session.commit()
        flash('Note updated', 'success')

    return redirect(url_for('view', id=note.reading_material_id))


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


# Tag management routes
@app.route('/tags')
def tags():
    all_tags = Tag.query.order_by(Tag.name).all()
    # Get usage count for each tag
    tag_data = []
    for tag in all_tags:
        count = tag.reading_materials.count()
        tag_data.append({'tag': tag, 'count': count})
    return render_template('tags.html', tags=tag_data)


@app.route('/tags/add', methods=['GET', 'POST'])
def add_tag():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        color = request.form.get('color') or Tag.random_color()

        if not name:
            flash('Tag name is required', 'error')
            return redirect(url_for('add_tag'))

        # Case-insensitive check for existing tag
        if Tag.query.filter(Tag.name.ilike(name)).first():
            flash('A tag with this name already exists', 'error')
            return redirect(url_for('add_tag'))

        tag = Tag(name=name, color=color)
        db.session.add(tag)
        db.session.commit()
        flash('Tag added successfully', 'success')
        return redirect(url_for('tags'))

    # Pass a random color for the preview default
    return render_template('tag_form.html', tag=None, default_color=Tag.random_color())


@app.route('/tags/edit/<int:id>', methods=['GET', 'POST'])
def edit_tag(id):
    tag = Tag.query.get_or_404(id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        color = request.form.get('color', 'gray')

        if not name:
            flash('Tag name is required', 'error')
            return redirect(url_for('edit_tag', id=id))

        # Case-insensitive check for existing tag
        existing = Tag.query.filter(Tag.name.ilike(name)).first()
        if existing and existing.id != tag.id:
            flash('A tag with this name already exists', 'error')
            return redirect(url_for('edit_tag', id=id))

        tag.name = name
        tag.color = color
        db.session.commit()
        flash('Tag updated successfully', 'success')
        return redirect(url_for('tags'))

    return render_template('tag_form.html', tag=tag)


@app.route('/tags/delete/<int:id>', methods=['POST'])
def delete_tag(id):
    tag = Tag.query.get_or_404(id)

    # Check if any reading materials use this tag
    if tag.reading_materials.count() > 0:
        flash('Cannot delete tag that is in use', 'error')
        return redirect(url_for('tags'))

    db.session.delete(tag)
    db.session.commit()
    flash('Tag deleted', 'success')
    return redirect(url_for('tags'))


@app.route('/api/tags')
def api_tags():
    query = request.args.get('q', '').strip()
    if query:
        tags = Tag.query.filter(Tag.name.ilike(f'%{query}%')).order_by(Tag.name).all()
    else:
        tags = Tag.query.order_by(Tag.name).all()
    return jsonify([{'id': tag.id, 'name': tag.name, 'color': tag.color or 'gray'} for tag in tags])


@app.route('/api/tags/<int:id>/color', methods=['POST'])
def api_update_tag_color(id):
    tag = Tag.query.get_or_404(id)
    data = request.get_json()
    color = data.get('color', 'gray')

    if color in Tag.TAG_COLORS:
        tag.color = color
        db.session.commit()
        return jsonify({'id': tag.id, 'name': tag.name, 'color': tag.color})

    return jsonify({'error': 'Invalid color'}), 400


@app.route('/api/tags/create', methods=['POST'])
def api_create_tag():
    data = request.get_json()
    name = data.get('name', '').strip()

    if not name:
        return jsonify({'error': 'Tag name is required'}), 400

    # Case-insensitive check for existing tag
    existing = Tag.query.filter(Tag.name.ilike(name)).first()
    if existing:
        return jsonify({'id': existing.id, 'name': existing.name, 'color': existing.color or 'gray'})

    tag = Tag(name=name, color=Tag.random_color())
    db.session.add(tag)
    db.session.commit()
    return jsonify({'id': tag.id, 'name': tag.name, 'color': tag.color})


@app.route('/api/item/<int:id>/update', methods=['POST'])
def api_update_item(id):
    item = ReadingMaterial.query.get_or_404(id)
    data = request.get_json()

    field = data.get('field')
    value = data.get('value')

    if field == 'title':
        if not value or not value.strip():
            return jsonify({'error': 'Title is required'}), 400
        item.title = value.strip()
    elif field == 'link':
        item.link = value.strip() if value else None
    elif field == 'status_id':
        item.status_id = int(value) if value else None
    elif field == 'chapter_current':
        item.chapter_current = max(0, int(value) if value else 0)
    elif field == 'chapter_total':
        item.chapter_total = int(value) if value else None
    elif field == 'notes':
        item.notes = value.strip() if value else None
    elif field == 'tags':
        # value is a list of tag names
        item.tags.clear()
        if value:
            for tag_name in value:
                tag_name = tag_name.strip()
                if tag_name:
                    # Case-insensitive search for existing tag
                    tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
                    if not tag:
                        tag = Tag(name=tag_name, color=Tag.random_color())
                        db.session.add(tag)
                    item.tags.append(tag)
    else:
        return jsonify({'error': 'Invalid field'}), 400

    db.session.commit()

    return jsonify({
        'success': True,
        'item': {
            'id': item.id,
            'title': item.title,
            'link': item.link,
            'status_id': item.status_id,
            'status_display': item.status_display,
            'status_color': item.status_color,
            'chapter_current': item.chapter_current,
            'chapter_total': item.chapter_total,
            'progress_percent': item.progress_percent,
            'tags': [tag.name for tag in item.tags]
        }
    })


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
