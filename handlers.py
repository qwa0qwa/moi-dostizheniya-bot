import logging
from pathlib import Path
from datetime import date

from max_api import MaxApiClient, MaxApiError
from security import normalize_text, parse_birth_date, parse_full_name
from documents import safe_document_path, make_document_filename

log=logging.getLogger(__name__)

def keyboard(rows):
    return [{"type":"inline_keyboard","payload":{"buttons":rows}}]

def back_button(target="menu:home"):
    return [[{"type":"callback","text":"⬅️ Назад","payload":target}]]

def home_keyboard():
    return keyboard([
      [{"type":"callback","text":"Моё портфолио","payload":"menu:portfolio"}],
      [{"type":"callback","text":"Найти документы","payload":"menu:find"}],
      [{"type":"callback","text":"Мой профиль","payload":"menu:profile"}],
      [{"type":"callback","text":"Для методистов","payload":"menu:methodist"}],
      [{"type":"callback","text":"Помощь","payload":"menu:help"}]
    ])

async def show_screen(api,db,uid,text,buttons=None):
    """Поддерживает один актуальный экран бота: редактирует старый или заменяет его."""
    mid=db.get_screen_message(uid)
    attachments=buttons or []
    if mid:
        try:
            await api.edit_message(mid,text,attachments)
            return
        except MaxApiError:
            log.warning("Не удалось отредактировать экран %s; заменяю его",mid)
            try:
                await api.delete_message(mid)
            except MaxApiError:
                log.warning("Не удалось удалить устаревший экран %s",mid)
    result=await api.send_message(uid,text,attachments)
    new_mid=extract_mid(result)
    if new_mid:
        db.set_screen_message(uid,new_mid)
    else:
        log.warning("MAX не вернул mid нового экранного сообщения: %r",result)

def extract_mid(result):
    """Извлекает mid из вариантов структуры ответа MAX и callback update."""
    if not isinstance(result,dict):
        return None
    for key in ("mid", "message_id"):
        value=result.get(key)
        if isinstance(value,str) and value:
            return value
    for key in ("message", "body", "callback"):
        value=result.get(key)
        if isinstance(value,dict):
            found=extract_mid(value)
            if found:
                return found
    return None

def callback_message_mid(update):
    callback=update.get("callback") or {}
    return extract_mid({"message": update.get("message"), "callback": callback})

async def methodist_screen(api,db,uid):
    application=db.get_methodist(uid)
    if application and application["status"]=="approved":
        db.clear_session(uid)
        await show_screen(api,db,uid,
            "Кабинет методиста\n\nСтатус: доступ подтверждён ✓\n"
            f"Организация: {application['organization']}\n\n"
            "Ваш аккаунт методиста активен.",
            keyboard([[{"type":"callback","text":"➕ Добавить документ","payload":"methodist:add_doc"}],
                      [{"type":"callback","text":"📚 Мои документы","payload":"methodist:my_docs"}],
                      *back_button("menu:home")]))
    elif application and application["status"]=="pending":
        db.clear_session(uid)
        await show_screen(api,db,uid,
            "Заявка методиста уже отправлена и ожидает рассмотрения.\n\n"
            f"Организация: {application['organization']}",
            keyboard(back_button("menu:home")))
    else:
        db.set_session(uid,"methodist")
        intro="Заявка ранее была отклонена. Ты можешь отправить её повторно.\n\n" if application and application["status"]=="rejected" else ""
        await show_screen(api,db,uid,intro+
            "Для методистов\n\nЧтобы подать заявку, введи ФИО и название организации через точку с запятой.\n"
            "Пример: Иванов Иван; Школа №1.",
            keyboard(back_button("menu:home")))

async def home(api,db,uid):
    db.clear_session(uid)
    await show_screen(api,db,uid,
      "Привет! Это бот «Мои достижения».\nВыбери нужный раздел:",home_keyboard())


def admin_keyboard():
    return keyboard([
      [{"type":"callback","text":"Заявки методистов","payload":"admin:applications"}],
      [{"type":"callback","text":"Организации","payload":"admin:organizations"}],
      [{"type":"callback","text":"Методисты","payload":"admin:methodists"}],
      [{"type":"callback","text":"Статистика","payload":"admin:stats"}],
      [{"type":"callback","text":"Главное меню","payload":"menu:home"}]
    ])

async def admin_home(api,db,uid):
    stats=db.admin_stats()
    text=("Панель администратора\n\n"
          f"Пользователей: {stats['users']}\n"
          f"Документов: {stats['documents']}\n"
          f"Организаций: {stats['organizations']}\n"
          f"Одобренных методистов: {stats['methodists']}\n"
          f"Ожидают проверки: {stats['pending_methodists']}\n\n"
          "Выбери действие:")
    db.clear_session(uid)
    await show_screen(api,db,uid,text,admin_keyboard())

async def admin_stats_view(api,db,uid):
    s=db.admin_stats()
    text=("Статистика проекта\n\n"
          f"Пользователей: {s['users']}\n"
          f"Документов: {s['documents']}\n"
          f"Организаций: {s['organizations']}\n"
          f"Одобренных методистов: {s['methodists']}\n"
          f"Заявок ожидают: {s['pending_methodists']}")
    await show_screen(api,db,uid,text,keyboard(back_button("admin:home")))

async def admin_applications_view(api,db,uid):
    apps=db.pending_methodists()
    if not apps:
        await show_screen(api,db,uid,"Новых заявок методистов нет.",keyboard(back_button("admin:home")))
        return
    lines=["Заявки методистов (первые 10):"]
    rows=[]
    for app in apps[:10]:
        lines.append(f"\n{app['display_name']}\nОрганизация: {app['organization']}\nID: {app['user_id']}")
        rows.append([
          {"type":"callback","text":f"Одобрить {app['user_id']}","payload":f"admin:approve:{app['user_id']}"},
          {"type":"callback","text":f"Отклонить {app['user_id']}","payload":f"admin:reject:{app['user_id']}"}
        ])
    rows += back_button("admin:home")
    await show_screen(api,db,uid,"\n".join(lines),keyboard(rows))

async def admin_organizations_view(api,db,uid):
    orgs=db.organizations()
    lines=["Образовательные организации:"]
    rows=[]
    for i,name in enumerate(orgs[:25]):
        lines.append(f"\n{i+1}. {name}")
        rows.append([{"type":"callback","text":f"Удалить: {name[:42]}","payload":f"admin:delete_org:{i}"}])
    if not orgs: lines.append("Пока нет добавленных организаций.")
    rows.append([{"type":"callback","text":"Добавить организацию","payload":"admin:add_org"}])
    rows += back_button("admin:home")
    db.set_session(uid,"admin_org_list",{"organizations":orgs[:25]})
    await show_screen(api,db,uid,"\n".join(lines),keyboard(rows))

async def admin_methodists_view(api,db,uid):
    people=db.approved_methodists()
    lines=["Одобренные методисты:"]
    rows=[]
    for person in people[:25]:
        lines.append(f"\n{person['display_name']}\n{person['organization']}\nID: {person['user_id']}")
        rows.append([{"type":"callback","text":f"Отозвать доступ: {person['display_name'][:35]}","payload":f"admin:revoke_methodist:{person['user_id']}"}])
    if not people: lines.append("Пока нет одобренных методистов.")
    rows += back_button("admin:home")
    await show_screen(api,db,uid,"\n".join(lines),keyboard(rows))

async def begin_add_document(api,db,uid):
    person=db.get_methodist(uid)
    if not person or person["status"]!="approved":
        await show_screen(api,db,uid,"Добавлять документы могут только одобренные методисты.",keyboard(back_button("menu:methodist")))
        return
    db.set_session(uid,"doc_full_name",{"organization":person["organization"]})
    await show_screen(api,db,uid,"Добавление документа\n\nШаг 1 из 7. Введи ФИО получателя одной строкой: фамилия, имя, отчество. Если отчества нет, укажи только фамилию и имя.",keyboard(back_button("menu:methodist")))

async def methodist_documents_view(api,db,uid):
    db.clear_session(uid)
    person=db.get_methodist(uid)
    if not person or person["status"]!="approved":
        await methodist_screen(api,db,uid); return
    docs=db.methodist_documents(person["organization"],100)
    lines=[f"Документы организации {person['organization']}:\nВыбери документ для редактирования или удаления."]
    buttons=[]
    for d in docs[:25]:
        fullname=" ".join(x for x in (d.get("surname"),d.get("first_name"),d.get("patronymic")) if x)
        lines.append(f"\n{d.get('title') or 'Без названия'}\nПолучатель: {fullname}\nМероприятие: {d.get('event_name') or '—'}")
        buttons.append([{"type":"callback","text":f"✏️ {str(d.get('title') or 'Документ')[:45]}","payload":f"methodist:edit_doc:{d['id']}"}])
    if not docs: lines.append("Документов пока нет.")
    buttons.append([{"type":"callback","text":"➕ Добавить документ","payload":"methodist:add_doc"}])
    buttons += back_button("menu:methodist")
    await show_screen(api,db,uid,"\n".join(lines),keyboard(buttons))

async def methodist_edit_document_view(api,db,uid,doc_id):
    db.clear_session(uid)
    person=db.get_methodist(uid)
    if not person or person["status"]!="approved":
        await methodist_screen(api,db,uid); return
    d=db.get_methodist_document(doc_id,person["organization"])
    if not d:
        await show_screen(api,db,uid,"Документ не найден или уже удалён.",keyboard(back_button("methodist:my_docs"))); return
    fullname=" ".join(x for x in (d.get("surname"),d.get("first_name"),d.get("patronymic")) if x)
    text=(f"{d.get('title') or 'Без названия'}\nПолучатель: {fullname}\n"
          f"Дата рождения: {d.get('birth_date') or '—'}\nТип: {d.get('document_type') or '—'}\n"
          f"Программа: {d.get('program_context') or '—'}\nМероприятие: {d.get('event_name') or '—'}\n"
          f"Дата выдачи: {d.get('issue_date') or '—'}\nФайл: {d.get('file_name') or '—'}\n\nЧто изменить?")
    fields=[("ФИО получателя","fullname"),("Дату рождения","birth_date"),("Название документа","title"),
            ("Программу","program_context"),("Тип документа","document_type"),("Мероприятие","event_name"),("Дату выдачи","issue_date"),("Файл","file")]
    buttons=[[{"type":"callback","text":f"Изменить: {label}","payload":f"methodist:edit_field:{doc_id}:{field}"}] for label,field in fields]
    buttons.append([{"type":"callback","text":"🗑 Удалить документ","payload":f"methodist:delete_doc:{doc_id}"}])
    buttons += back_button("methodist:my_docs")
    await show_screen(api,db,uid,text,keyboard(buttons))

async def begin_profile(api,db,uid):
    db.set_session(uid,"profile_name")
    await show_screen(api,db,uid,
      "Мой профиль\n\nВведи ФИО (отчество необязательно).",
      keyboard(back_button("menu:home")))

async def profile_view(api,db,uid):
    p=db.get_profile(uid)
    if not p or not p.get("birth_date"):
        await begin_profile(api,db,uid); return
    name=" ".join(x for x in (p["surname"],p["first_name"],p["patronymic"]) if x)
    await show_screen(api,db,uid,
      f"Мой профиль\n\nФИО: {name}\nДата рождения: {p['birth_date']}\n\nЧтобы изменить данные, нажми «Изменить профиль».",
      keyboard([[{"type":"callback","text":"Изменить профиль","payload":"profile:edit"}],
                *back_button("menu:home")]))

async def begin_find(api,db,uid):
    p=db.get_profile(uid)
    if not p or not p.get("birth_date"):
        db.set_session(uid,"profile_name")
        await show_screen(api,db,uid,"Сначала заполни профиль.\n\nВведи ФИО (отчество необязательно).",
                          keyboard(back_button("menu:home")))
        return
    db.set_session(uid,"find_org_text",{})
    await show_screen(api,db,uid,
      "Найти документы\n\nНачни вводить название организации и отправь сообщение. Я покажу подходящие варианты кнопками.",
      keyboard(back_button("menu:home")))

async def choose_organization(api,db,uid,org):
    db.set_session(uid,"find_program",{"organization":org})
    await show_screen(api,db,uid,
      f"Организация: {org}\n\nВведи программу, в рамках которой получен документ.\nМожно написать «все», чтобы показать все документы этой организации.",
      keyboard(back_button("menu:find")))


async def show_docs(api,db,uid,docs,settings=None):
    if not docs:
        await show_screen(api,db,uid,"Документы по выбранным данным не найдены.",
                          keyboard([[{"type":"callback","text":"Изменить поиск","payload":"menu:find"}],
                                    *back_button("menu:home")]))
        return
    lines=[f"Найдено документов: {len(docs)}. Выбери документ, чтобы получить файл:"]
    buttons=[]
    for d in docs[:25]:
        title=d.get("title") or d.get("document_type") or "Документ"
        lines.append(f"\n#{d['id']} — {title}\n{d.get('organization') or '—'} · {d.get('issue_date') or 'дата не указана'}")
        buttons.append([{"type":"callback","text":f"📄 #{d['id']} {str(title)[:38]}","payload":f"doc:{d['id']}"}])
    buttons.append([{"type":"callback","text":"Найти ещё","payload":"menu:find"}])
    buttons += back_button("menu:home")
    await show_screen(api,db,uid,"\n".join(lines),keyboard(buttons))

async def handle_callback(update,api,db,settings):
    cb=update.get("callback") or {}; user=cb.get("user") or {}
    uid=user.get("user_id"); payload=cb.get("payload","")
    if not isinstance(uid,int): return
    callback_id=cb.get("callback_id")
    if callback_id:
        try: await api.answer_callback(callback_id,"Обрабатываю нажатие…")
        except MaxApiError: log.warning("Callback acknowledgement failed")
    if payload=="menu:home": await home(api,db,uid)
    elif payload=="menu:profile": await profile_view(api,db,uid)
    elif payload=="profile:edit": await begin_profile(api,db,uid)
    elif payload=="menu:find": await begin_find(api,db,uid)
    elif payload=="menu:portfolio":
        p=db.get_profile(uid)
        if not p or not p.get("birth_date"):
            await begin_profile(api,db,uid)
        else: await show_docs(api,db,uid,db.search_documents(p),settings)
    elif payload=="menu:methodist":
        await methodist_screen(api,db,uid)
    elif payload=="menu:help":
        await show_screen(api,db,uid,"Помощь\n\nЗаполни профиль, затем открой «Моё портфолио» или «Найти документы».",
                          keyboard(back_button("menu:home")))
    elif payload.startswith("findorg:"):
        try:
            idx=int(payload.split(":",1)[1])
            session=db.get_session(uid)
            matches=(session[1].get("matches",[]) if session else [])
            org=matches[idx]
        except (ValueError,IndexError,TypeError):
            return
        await choose_organization(api,db,uid,org)
    elif payload=="findorgcustom":
        session=db.get_session(uid)
        org=(session[1].get("query","") if session else "").strip()
        if org:
            await choose_organization(api,db,uid,org)
    elif payload.startswith("doc:"):
        try: doc_id=int(payload.split(":",1)[1])
        except ValueError: return
        item=db.get_document(doc_id,uid)
        if not item:
            await show_screen(api,db,uid,"Не удалось подтвердить принадлежность документа профилю.",
                              keyboard(back_button("menu:home"))); return
        try:
            path=safe_document_path(item["file_path"],settings.documents)
            caption=(f"📄 {item.get('title') or 'Документ'}\n"
                     f"Тип: {item.get('document_type') or '—'}\n"
                     f"Организация: {item.get('organization') or '—'}\n"
                     f"Программа: {item.get('program_context') or '—'}\n"
                     f"Мероприятие: {item.get('event_name') or '—'}\n"
                     f"Дата выдачи: {item.get('issue_date') or '—'}")
            await api.send_file(uid,path,caption)
            await show_screen(api,db,uid,"Документ отправлен.",
                              keyboard(back_button("menu:portfolio")))
        except Exception:
            log.exception("Document delivery failed")
            await show_screen(api,db,uid,"Не удалось отправить файл. Обратись к администратору.",
                              keyboard(back_button("menu:portfolio")))
    elif payload=="methodist:add_doc":
        await begin_add_document(api,db,uid)
    elif payload=="methodist:my_docs":
        await methodist_documents_view(api,db,uid)
    elif payload.startswith("methodist:edit_doc:"):
        try: doc_id=int(payload.rsplit(":",1)[1])
        except ValueError: return
        await methodist_edit_document_view(api,db,uid,doc_id)
    elif payload.startswith("methodist:edit_field:"):
        parts=payload.split(":")
        if len(parts)!=4: return
        try: doc_id=int(parts[2])
        except ValueError: return
        field=parts[3]
        person=db.get_methodist(uid)
        doc=db.get_methodist_document(doc_id,person["organization"]) if person and person["status"]=="approved" else None
        if not doc: await methodist_documents_view(api,db,uid); return
        if field=="file":
            db.set_session(uid,"doc_edit_file",{"doc_id":doc_id,"organization":person["organization"]})
            prompt="Прикрепи новый файл PDF, JPG или PNG. Старый файл будет заменён после успешной загрузки."
        else:
            db.set_session(uid,"doc_edit_value",{"doc_id":doc_id,"organization":person["organization"],"field":field})
            prompt={"fullname":"Введи новое ФИО одной строкой.","birth_date":"Введи новую дату рождения ДД.ММ.ГГГГ.","title":"Введи новое название документа.","program_context":"Введи новое название программы.","document_type":"Введи новый тип документа.","event_name":"Введи новое мероприятие или дефис, если его нет.","issue_date":"Введи новую дату выдачи ДД.ММ.ГГГГ или дефис."}.get(field,"Введи новое значение.")
        await show_screen(api,db,uid,prompt,keyboard(back_button(f"methodist:edit_doc:{doc_id}")))
    elif payload.startswith("methodist:delete_doc:"):
        try: doc_id=int(payload.rsplit(":",1)[1])
        except ValueError: return
        person=db.get_methodist(uid)
        doc=db.get_methodist_document(doc_id,person["organization"]) if person and person["status"]=="approved" else None
        if not doc: await methodist_documents_view(api,db,uid); return
        db.set_session(uid,"doc_confirm_delete",{"doc_id":doc_id,"organization":person["organization"]})
        await show_screen(api,db,uid,f"Удалить документ «{doc.get('title') or 'Без названия'}»?\nОн исчезнет из поиска и портфолио.",keyboard([[{"type":"callback","text":"Да, удалить","payload":"methodist:confirm_delete_doc"}],*back_button(f"methodist:edit_doc:{doc_id}")]))
    elif payload=="methodist:confirm_delete_doc":
        session=db.get_session(uid); person=db.get_methodist(uid)
        if session and session[0]=="doc_confirm_delete" and person and person["status"]=="approved":
            data=session[1]
            if data.get("organization")==person["organization"]:
                old_doc=db.get_methodist_document(data["doc_id"],person["organization"])
                if db.disable_document(data["doc_id"],person["organization"]) and old_doc:
                    try: safe_document_path(old_doc["file_path"],settings.documents).unlink(missing_ok=True)
                    except Exception: log.warning("Не удалось удалить файл отключённого документа")
        db.clear_session(uid); await methodist_documents_view(api,db,uid)
    elif payload.startswith("admin:"):
        if uid not in settings.admins:
            await show_screen(api,db,uid,"Недостаточно прав.",keyboard(back_button("menu:home"))); return
        if payload=="admin:home":
            await admin_home(api,db,uid)
        elif payload=="admin:stats":
            await admin_stats_view(api,db,uid)
        elif payload=="admin:applications":
            await admin_applications_view(api,db,uid)
        elif payload=="admin:organizations":
            await admin_organizations_view(api,db,uid)
        elif payload=="admin:methodists":
            await admin_methodists_view(api,db,uid)
        elif payload.startswith("admin:delete_org:"):
            try: idx=int(payload.rsplit(":",1)[1])
            except ValueError: return
            session=db.get_session(uid)
            orgs=session[1].get("organizations",[]) if session and session[0]=="admin_org_list" else []
            if 0<=idx<len(orgs):
                db.set_session(uid,"admin_confirm_delete_org",{"organization":orgs[idx]})
                await show_screen(api,db,uid,f"Отключить организацию «{orgs[idx]}»?\n\nСуществующие документы останутся в базе, но организация исчезнет из поиска.",
                  keyboard([[{"type":"callback","text":"Да, отключить","payload":"admin:confirm_delete_org"}],*back_button("admin:organizations")]))
        elif payload=="admin:confirm_delete_org":
            session=db.get_session(uid)
            org=session[1].get("organization") if session and session[0]=="admin_confirm_delete_org" else None
            if org: db.delete_organization(org)
            db.clear_session(uid); await admin_organizations_view(api,db,uid)
        elif payload.startswith("admin:revoke_methodist:"):
            try: target=int(payload.rsplit(":",1)[1])
            except ValueError: return
            changed=db.revoke_methodist(target)
            if changed:
                try: await api.send_message(target,"Доступ методиста к кабинету отозван администратором.")
                except MaxApiError: log.warning("Не удалось уведомить методиста %s",target)
            await admin_methodists_view(api,db,uid)
        elif payload=="admin:add_org":
            db.set_session(uid,"admin_add_org")
            await show_screen(api,db,uid,"Введи полное название новой организации.",
                              keyboard(back_button("admin:organizations")))
        else:
            parts=payload.split(":")
            if len(parts)==3 and parts[1] in ("approve","reject"):
                try:
                    target=int(parts[2])
                except ValueError:
                    return
                approved=parts[1]=="approve"
                changed=db.review_methodist(target,uid,approved)
                application=db.get_methodist(target)
                if changed:
                    status="одобрена" if approved else "отклонена"
                    try:
                        await api.send_message(target,
                            f"Твоя заявка методиста {status}." +
                            (f"\nОрганизация: {application['organization']}" if application else ""))
                    except MaxApiError:
                        log.warning("Не удалось уведомить методиста %s о решении",target)
                elif application:
                    status="уже одобрена" if application["status"]=="approved" else (
                        "уже отклонена" if application["status"]=="rejected" else "уже обработана")
                else:
                    status="не найдена"
                source_mid=callback_message_mid(update)
                if source_mid:
                    try:
                        await api.delete_message(source_mid)
                    except MaxApiError:
                        try:
                            await api.edit_message(source_mid,
                                f"Заявка пользователя {target}: {status}.", [])
                        except MaxApiError:
                            log.warning("Не удалось убрать обработанную заявку из чата")
                await admin_applications_view(api,db,uid)


async def handle_update(update,api,db,settings):
    typ=update.get("update_type")
    if typ=="message_callback":
        await handle_callback(update,api,db,settings); return
    if typ=="bot_started":
        user=update.get("user") or {}; uid=user.get("user_id")
        if isinstance(uid,int): db.remember_user(uid); await home(api,db,uid)
        return
    if typ!="message_created": return
    msg=update.get("message") or {}; sender=msg.get("sender") or {}; body=msg.get("body") or {}
    uid=sender.get("user_id"); text=(body.get("text") or "").strip()
    attachments=body.get("attachments") or []
    if not isinstance(uid,int) or (not text and not attachments): return
    db.remember_user(uid)
    # Удаляем предыдущий экран бота и создаём следующий внизу переписки.
    # В личном диалоге MAX не разрешает боту удалять сообщения пользователя.
    old_mid=db.get_screen_message(uid)
    if old_mid:
        try: await api.delete_message(old_mid)
        except MaxApiError: log.debug("Не удалось удалить старое меню %s",old_mid)
        db.set_screen_message(uid,"")
    cmd=text.split()[0].split("@")[0].lower() if text else ""
    if cmd=="/myid":
        await api.send_message(uid,f"Твой MAX user ID: {uid}")
        return
    if cmd=="/admin":
        if uid not in settings.admins:
            await show_screen(api,db,uid,"Недостаточно прав для доступа к панели администратора.",
                              keyboard(back_button("menu:home")))
        else:
            await admin_home(api,db,uid)
        return
    if cmd=="/start": await home(api,db,uid); return
    if cmd=="/profile": await begin_profile(api,db,uid); return
    if cmd=="/find": await begin_find(api,db,uid); return
    if cmd=="/portfolio":
        p=db.get_profile(uid)
        if p and p.get("birth_date"): await show_docs(api,db,uid,db.search_documents(p),settings)
        else: await begin_profile(api,db,uid)
        return
    if cmd=="/methodist":
        await methodist_screen(api,db,uid); return
    if cmd=="/applications":
        if uid not in settings.admins:
            await show_screen(api,db,uid,"Недостаточно прав.",keyboard(back_button("menu:home"))); return
        await admin_applications_view(api,db,uid)
        return
    session=db.get_session(uid)
    if not session:
        await show_screen(api,db,uid,"Выбери раздел в меню.",home_keyboard()); return
    stage,payload=session
    if stage.startswith("doc_"):
        if stage in ("doc_surname", "doc_first_name", "doc_patronymic"):
            db.set_session(uid,"doc_full_name",{"organization":payload.get("organization", "")})
            await show_screen(api,db,uid,"Форма добавления обновилась. Введи ФИО получателя одной строкой: фамилия, имя, отчество (если есть).",keyboard(back_button("menu:methodist")))
            return
        person=db.get_methodist(uid)
        if not person or person["status"]!="approved":
            db.clear_session(uid); await methodist_screen(api,db,uid); return
        if stage=="doc_edit_file":
            data=payload
            attachment=next((a for a in attachments if a.get("type") in ("file","image")),None)
            if not attachment:
                await show_screen(api,db,uid,"Прикрепи PDF, JPG или PNG.",keyboard(back_button(f"methodist:edit_doc:{data.get('doc_id')}"))); return
            ap=attachment.get("payload") or {}; url=ap.get("url")
            filename=attachment.get("filename") or ap.get("filename") or ""
            ext=Path(filename).suffix.lower() or (".jpg" if attachment.get("type")=="image" else "")
            if ext not in (".pdf",".jpg",".jpeg",".png") or not url:
                await show_screen(api,db,uid,"Формат не поддерживается. Отправь PDF, JPG или PNG.",keyboard(back_button(f"methodist:edit_doc:{data.get('doc_id')}"))); return
            old_doc=db.get_methodist_document(data["doc_id"],person["organization"])
            stored=make_document_filename((old_doc or {}).get("title") or "Документ",ext,settings.documents)
            try:
                await api.download_attachment(url,settings.documents/stored)
                old=old_doc
                ok=db.update_document(data["doc_id"],person["organization"],{"file_path":stored,"file_name":filename or stored})
                if not ok: raise ValueError("Документ больше недоступен")
                if old:
                    try: safe_document_path(old["file_path"],settings.documents).unlink(missing_ok=True)
                    except Exception: log.warning("Не удалось удалить старый файл документа")
                db.clear_session(uid)
                await methodist_edit_document_view(api,db,uid,data["doc_id"])
            except Exception:
                log.exception("Document replacement failed")
                (settings.documents/stored).unlink(missing_ok=True)
                await show_screen(api,db,uid,"Не удалось заменить файл. Попробуй ещё раз.",keyboard(back_button(f"methodist:edit_doc:{data.get('doc_id')}")))
            return
        if stage=="doc_edit_value":
            field=payload.get("field"); value=text.strip(); values={}
            if field=="fullname":
                parsed=parse_full_name(value)
                if not parsed:
                    await show_screen(api,db,uid,"Укажи фамилию и имя, отчество — по желанию.",keyboard(back_button(f"methodist:edit_doc:{payload.get('doc_id')}"))); return
                values.update(surname=parsed[0],first_name=parsed[1],patronymic=parsed[2])
            elif field in ("birth_date","issue_date"):
                if value!="-":
                    parsed=parse_birth_date(value)
                    if not parsed:
                        await show_screen(api,db,uid,"Дата должна быть в формате ДД.ММ.ГГГГ или дефис.",keyboard(back_button(f"methodist:edit_doc:{payload.get('doc_id')}"))); return
                    value=parsed
                else: value=""
                values[field]=value
            else:
                if field in ("event_name",) and value=="-": value=""
                if not value and field in ("title",):
                    await show_screen(api,db,uid,"Название документа не может быть пустым.",keyboard(back_button(f"methodist:edit_doc:{payload.get('doc_id')}"))); return
                values[field]=value
            ok=db.update_document(payload["doc_id"],person["organization"],values)
            db.clear_session(uid)
            if ok: await methodist_edit_document_view(api,db,uid,payload["doc_id"])
            else: await methodist_documents_view(api,db,uid)
            return
        if stage=="doc_full_name":
            parsed=parse_full_name(text)
            if not parsed:
                await show_screen(api,db,uid,"ФИО не распознано. Введи фамилию и имя, отчество — если есть.",keyboard(back_button("menu:methodist"))); return
            payload.update(surname=parsed[0],first_name=parsed[1],patronymic=parsed[2])
            db.set_session(uid,"doc_birth_date",payload)
            await show_screen(api,db,uid,"Шаг 2 из 7. Введи дату рождения: ДД.ММ.ГГГГ.",keyboard(back_button("menu:methodist"))); return
        fields={
          "doc_birth_date":("birth_date","doc_title"),
          "doc_title":("title","doc_program"),
          "doc_program":("program_context","doc_type"),
          "doc_type":("document_type","doc_event"),
          "doc_event":("event_name","doc_issue_date"),
          "doc_issue_date":("issue_date","doc_file")
        }
        if stage=="doc_file":
            attachment=next((a for a in attachments if a.get("type") in ("file","image")),None)
            if not attachment:
                await show_screen(api,db,uid,"Прикрепи PDF, JPG или PNG как файл/изображение.",keyboard(back_button("menu:methodist"))); return
            payload_file=attachment.get("payload") or {}; url=payload_file.get("url")
            filename=attachment.get("filename") or payload_file.get("filename") or ""
            ext=Path(filename).suffix.lower()
            if not ext and attachment.get("type")=="image": ext=".jpg"
            if ext not in (".pdf",".jpg",".jpeg",".png") or not url:
                await show_screen(api,db,uid,"Формат не поддерживается. Отправь PDF, JPG или PNG.",keyboard(back_button("menu:methodist"))); return
            data=payload.copy(); data["organization"]=person["organization"]
            settings.documents.mkdir(parents=True,exist_ok=True)
            stored=make_document_filename(data.get("title") or "Документ",ext,settings.documents)
            try:
                await api.download_attachment(url,settings.documents/stored)
                data["file_path"]=stored; data["file_name"]=filename or stored
                db.add_document(data); db.clear_session(uid)
                await show_screen(api,db,uid,"Документ успешно добавлен в базу и теперь доступен для поиска.",
                  keyboard([[{"type":"callback","text":"Добавить ещё","payload":"methodist:add_doc"}],*back_button("menu:methodist")]))
            except Exception:
                log.exception("Document save failed")
                (settings.documents/stored).unlink(missing_ok=True)
                await show_screen(api,db,uid,"Не удалось сохранить файл. Попробуй отправить его ещё раз.",keyboard(back_button("menu:methodist")))
            return
        if stage in fields:
            key,next_stage=fields[stage]; value=text.strip()
            if key in ("birth_date","issue_date"):
                if value!="-":
                    parsed=parse_birth_date(value)
                    if not parsed:
                        await show_screen(api,db,uid,"Дата не распознана. Формат: ДД.ММ.ГГГГ или дефис.",keyboard(back_button("menu:methodist"))); return
                    value=parsed
                else: value=""
            elif key=="event_name" and value=="-": value=""
            if key=="title" and not value:
                await show_screen(api,db,uid,"Название документа обязательно.",keyboard(back_button("menu:methodist"))); return
            payload[key]=value; db.set_session(uid,next_stage,payload)
            prompts={"doc_title":"Шаг 3 из 7. Введи название документа.","doc_program":"Шаг 4 из 7. Введи название программы.","doc_type":"Шаг 5 из 7. Введи тип документа (диплом, грамота, сертификат и т. п.).","doc_event":"Шаг 6 из 7. Введи мероприятие или дефис.","doc_issue_date":"Шаг 7 из 7. Введи дату выдачи ДД.ММ.ГГГГ или дефис.","doc_file":"Теперь прикрепи сам документ: PDF, JPG или PNG."}
            await show_screen(api,db,uid,prompts[next_stage],keyboard(back_button("menu:methodist")))
            return
    if stage=="admin_add_org":
        if uid not in settings.admins:
            db.clear_session(uid)
            await show_screen(api,db,uid,"Недостаточно прав.",keyboard(back_button("menu:home")))
            return
        name=" ".join(text.split())
        if len(name)<3 or len(name)>180:
            await show_screen(api,db,uid,"Название должно содержать от 3 до 180 символов.",
                              keyboard(back_button("admin:organizations"))); return
        db.add_organization(name)
        db.clear_session(uid)
        await admin_organizations_view(api,db,uid)
    elif stage=="profile_name":
        parsed=parse_full_name(text)
        if not parsed:
            await show_screen(api,db,uid,"ФИО должно содержать фамилию и имя; отчество необязательно.",
                              keyboard(back_button("menu:home"))); return
        payload["name"]=parsed; db.set_session(uid,"profile_birth",payload)
        await show_screen(api,db,uid,"Теперь введи дату рождения в формате ДД.ММ.ГГГГ.",
                          keyboard(back_button("menu:profile")))
    elif stage=="profile_birth":
        birth=parse_birth_date(text)
        if not birth or birth>date.today().isoformat():
            await show_screen(api,db,uid,"Дата не распознана. Введи дату в формате ДД.ММ.ГГГГ.",
                              keyboard(back_button("menu:profile"))); return
        db.save_profile(uid,payload["name"],birth); db.clear_session(uid)
        await profile_view(api,db,uid)
    elif stage=="find_org_text":
        query=text.strip()
        if not query:
            return
        normalized=normalize_text(query)
        orgs=db.organizations()
        matches=[org for org in orgs if normalized in normalize_text(org)]
        exact=next((org for org in matches if normalize_text(org)==normalized),None)
        if exact:
            await choose_organization(api,db,uid,exact)
            return
        matches=matches[:10]
        db.set_session(uid,"find_org_text",{"query":query,"matches":matches})
        rows=[[{"type":"callback","text":org[:60],"payload":f"findorg:{i}"}]
              for i,org in enumerate(matches)]
        prompt=(f"Подсказки для «{query}» — выбери организацию:"
                if matches else f"По запросу «{query}» совпадений в списке нет.")
        rows.append([{"type":"callback","text":f"Использовать «{query[:45]}»","payload":"findorgcustom"}])
        rows += back_button("menu:find")
        await show_screen(api,db,uid,prompt,keyboard(rows))
    elif stage=="find_program":
        org=payload.get("organization","")
        query="" if text.casefold() in ("все","всё","-") else text
        p=db.get_profile(uid)
        docs=db.search_documents(p,query)
        docs=[d for d in docs if normalize_text(d.get("organization") or "")==normalize_text(org)]
        db.clear_session(uid)
        await show_docs(api,db,uid,docs,settings)
    elif stage=="methodist":
        if ";" not in text:
            await show_screen(api,db,uid,"Введи ФИО и организацию через точку с запятой.",
                              keyboard(back_button("menu:home"))); return
        name,org=[x.strip() for x in text.split(";",1)]
        if not name or not org:
            await show_screen(api,db,uid,"Нужно указать и ФИО, и организацию.",
                              keyboard(back_button("menu:home"))); return
        db.register_methodist(uid,name,org); db.clear_session(uid)
        await show_screen(api,db,uid,"Заявка методиста отправлена администратору.",
                          keyboard(back_button("menu:home")))
        for aid in settings.admins:
            try:
                await api.send_message(aid,f"Новая заявка методиста\nID: {uid}\n{name}\n{org}",
                  keyboard([[{"type":"callback","text":"Одобрить","payload":f"admin:approve:{uid}"},
                             {"type":"callback","text":"Отклонить","payload":f"admin:reject:{uid}"}]]))
            except MaxApiError: log.exception("Admin notification failed")
