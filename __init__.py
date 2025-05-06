""" Xiaomi miIO """
import datetime
import miio
import enum
from flask import redirect, render_template, request, jsonify
import miio.device
import miio.devicefactory
import miio.miioprotocol
from sqlalchemy import delete, or_
from app.database import session_scope, row2dict, db, get_now_to_utc
from app.authentication.handlers import handle_admin_required
from app.core.main.BasePlugin import BasePlugin
from plugins.xiio.models.xiioDevices import XiioDevices
from plugins.xiio.models.xiioProperties import XiioProperties
from plugins.xiio.models.xiioCommands import XiioCommands
from app.core.lib.object import callMethodThread, updatePropertyThread, setLinkToObject, removeLinkFromObject
from plugins.xiio.forms.SettingForms import SettingsForm

class xiio(BasePlugin):

    def __init__(self,app):
        super().__init__(app,__name__)
        self.title = "Xiaomi miIO"
        self.version = 1
        self.description = """This is a plugin for Xiaomi miIO devices"""
        self.category = "Devices"
        self.actions = ['cycle','search','widget']

    def initialization(self):
        pass

    def admin(self, request):
        op = request.args.get('op', '')
        id = request.args.get('id', '')

        if op == 'dicovery':
            # Используем функцию discover для поиска устройств
            devices = miio.Discovery.discover_mdns()
            self.logger.debug(devices)
            with session_scope() as session:
                for device in devices.values():
                    dev_rec = session.query(XiioDevices).filter(XiioDevices.device_id == device.device_id).one_or_none()
                    if not dev_rec:
                        dev_rec = XiioDevices()
                        dev_rec.ip = device.ip
                        dev_rec.device_id = device.device_id
                        dev_rec.device_type = type(device).__name__
                        dev_rec.title = type(device).__name__
                        session.add(dev_rec)
                        session.commit()

            return redirect(self.name)

        if op == 'edit':
            return render_template("xiio_device.html", id=id)

        if op == 'add':
            return render_template("xiio_device.html", id=None)

        if op == 'delete':
            sql = delete(XiioCommands).where(XiioCommands.device_id == id)
            db.session.execute(sql)
            sql = delete(XiioProperties).where(XiioProperties.device_id == id)
            db.session.execute(sql)
            sql = delete(XiioDevices).where(XiioDevices.id == id)
            db.session.execute(sql)
            db.session.commit()
            return redirect(self.name)

        settings = SettingsForm()
        if request.method == 'GET':
            settings.host.data = self.config.get('host','')
            settings.port.data = self.config.get('port',1883)
            settings.topic.data = self.config.get('topic','')
        else:
            if settings.validate_on_submit():
                self.config["host"] = settings.host.data
                self.config["port"] = settings.port.data
                self.config["topic"] = settings.topic.data
                self.saveConfig()
        devs = XiioDevices.query.order_by(XiioDevices.title).all()
        devices = []
        props = XiioProperties.query.order_by(XiioProperties.title).all()

        for device in devs:
            vdev = row2dict(device)
            av = [av for av in props if (av.device_id == device.id and av.property_name == 'online')]
            if av:
                vdev['online'] = av[0].value

            devices.append(vdev)

        content = {
            "form": settings,
            "devices": devices,
        }
        return self.render('xiio.html', content)

    def route_index(self):
        @self.blueprint.route('/xiio/device', methods=['POST'])
        @self.blueprint.route('/xiio/device/<device_id>', methods=['GET', 'POST'])
        @handle_admin_required
        def point_xi_device(device_id=None):
            with session_scope() as session:
                if request.method == "GET":
                    dev = session.query(XiioDevices).filter(XiioDevices.id == device_id).one()
                    device = row2dict(dev)
                    device['props'] = []
                    device['commands'] = []
                    props = session.query(XiioProperties).filter(XiioProperties.device_id == device_id).order_by(XiioProperties.title)
                    for prop in props:
                        item = row2dict(prop)
                        device['props'].append(item)
                    cmds = session.query(XiioCommands).filter(XiioCommands.device_id == device_id).all()
                    for cmd in cmds:
                        item = row2dict(cmd)
                        device['commands'].append(item)
                    return jsonify(device)
                if request.method == "POST":
                    data = request.get_json()
                    if data['id']:
                        device = session.query(XiioDevices).where(XiioDevices.id == int(data['id'])).one()
                    else:
                        device = XiioDevices()
                        session.add(device)
                        session.commit()

                    device.title = data['title']
                    device.ip = data['ip']
                    device.token = data['token']
                    device.update_period = data['update_period']

                    for prop in data['props']:
                        prop_rec = session.query(XiioProperties).filter(XiioProperties.device_id == device.id,XiioProperties.property_name == prop['property_name']).one()
                        if prop_rec.linked_object:
                            removeLinkFromObject(prop_rec.linked_object, prop_rec.linked_property, self.name)
                        prop_rec.linked_object = prop['linked_object']
                        prop_rec.linked_property = prop['linked_property']
                        prop_rec.linked_method = prop['linked_method']
                        prop_rec.command = prop['command']
                        if prop_rec.linked_object:
                            setLinkToObject(prop_rec.linked_object, prop_rec.linked_property, self.name)
                        prop_rec.title = prop['title']

                    session.commit()

                    return 'Device updated successfully', 200

        @self.blueprint.route('/xiio/delete_prop/<prop_id>', methods=['GET', 'POST'])
        @handle_admin_required
        def point_delprop(prop_id=None):
            with session_scope() as session:
                sql = delete(XiioProperties).where(XiioProperties.id == int(prop_id))
                session.execute(sql)
                session.commit()

        @self.blueprint.route('/xiio/command', methods=['POST'])
        @handle_admin_required
        def point_xiiocommand():
            data = request.get_json()
            res = self.command(data["device_name"], data["command"], data["params"])
            return str(res), 200

    def cyclic_task(self):
        if self.event.is_set():
            # Останавливаем цикл обработки сообщений
            pass
        else:
            with session_scope() as session:
                devices = session.query(XiioDevices).all()

                for dev in devices:
                    if dev.updated:
                        diff = get_now_to_utc() - dev.updated
                        period = dev.update_period if dev.update_period else 5
                        if diff < datetime.timedelta(seconds=period):
                            continue
                    device = None
                    try:
                        device = miio.devicefactory.DeviceFactory.create(dev.ip, dev.token)
                        self.logger.debug(device)
                        if dev.device_type != device.model:
                            dev.device_type = device.model
                            for cmd in device._device_group_commands.values():
                                command = XiioCommands()
                                command.device_id = dev.id
                                command.name = cmd.command_name
                                command.description = cmd.kwargs['help']
                                session.add(command)
                            session.commit()
                        self.setProperty(session, dev, 'online', 'Device online', 1)
                    except Exception as ex:
                        self.logger.debug(ex)
                        self.setProperty(session, dev, 'online', 'Device online', 0)
                        continue
                    try:
                        status = device.status()
                        # todo merge data for optimize update property
                        if len(status._descriptors) > 0:
                            for descriptor in status._descriptors.values():
                                value = getattr(status,descriptor.status_attribute)
                                self.setProperty(session, dev, descriptor.status_attribute, descriptor.name, value)
                        
                        for key in status.data.keys():
                            self.setProperty(session, dev, key, key, status.data[key])
                        dev.updated = get_now_to_utc()
                        session.commit()
                    except Exception as ex:
                        self.logger.debug(ex)
         
            self.event.wait(1.0)

    def setProperty(self, session, device, name, description, value):
        prop = session.query(XiioProperties).filter_by(device_id=device.id, property_name=name).one_or_none()
        if prop is None:
            prop = XiioProperties()
            prop.device_id = device.id
            prop.property_name = name
            prop.title = description
            session.add(prop)
            session.commit()
        
        if isinstance(value, enum.Enum):
            value = value.value

        if prop.value != str(value):
            old_value = prop.value
            prop.value = str(value)
            if value == 'on':
                value = 1
            if value == 'off':
                value = 0
            prop.updated = get_now_to_utc()
            session.commit()
            if prop.linked_object:
                if prop.linked_method:
                    callMethodThread(prop.linked_object + '.' + prop.linked_method, {'VALUE': value, 'NEW_VALUE': value, 'OLD_VALUE': old_value, 'TITLE': name}, self.name)
                if prop.linked_property:
                    updatePropertyThread(prop.linked_object + '.' + prop.linked_property, value, self.name)

    def changeLinkedProperty(self, obj, prop, val):
        with session_scope() as session:
            properties = session.query(XiioProperties).filter(XiioProperties.linked_object == obj, XiioProperties.linked_property == prop).all()
            if len(properties) == 0:
                from app.core.lib.object import removeLinkFromObject
                removeLinkFromObject(obj, prop, self.name)
                return
            for property in properties:
                dev = session.get(XiioDevices, property.device_id)
                try:
                    device = miio.devicefactory.DeviceFactory.create(dev.ip, dev.token)
                    command = property.command
                    if command == 'on' and str(val) == '0':
                        command = 'off'
                    elif command == 'off' and str(val) == '1':
                        command = 'on'
                    self._run_command(device, command, int(val))
                except Exception as ex:
                    self.logger.debug(ex)
                    continue

    def command(self, device_name, func, *args):
        with session_scope() as session:
            dev = session.query(XiioDevices).filter(XiioDevices.title == device_name).one_or_none()
            if dev:
                device = miio.devicefactory.DeviceFactory.create(dev.ip, dev.token)
                result = self._run_command(device, func, *args)
                return result
            return None

    def _run_command(self, device, command, *args, **kwargs):
        if hasattr(device, command):
            function = getattr(device, command)
            try:
                import inspect
                params = inspect.signature(function).parameters
                if len(params) == 0:
                    return function()
                else:
                    signature = inspect.signature(function)
                    bound_args = signature.bind(*args, **kwargs)
                    bound_args.apply_defaults()

                    # Приводим аргументы к нужным типам
                    for name, value in bound_args.arguments.items():
                        expected_type = signature.parameters[name].annotation
                        if expected_type is not inspect.Parameter.empty:
                            bound_args.arguments[name] = expected_type(value)

                    return function(*bound_args.args, **bound_args.kwargs)
                    #return function(args)
            except Exception as ex:
                self.logger.exception(ex)
        else:
            self.logger.error("Function '%s' not found in device %s.", command, device.__name__)
        return None

    def search(self, query: str) -> str:
        res = []
        devices = XiioDevices.query.filter(or_(XiioDevices.title.contains(query))).all()
        for device in devices:
            res.append({"url":f'xiio?op=edit&id={device.id}',
                        "title":f'{device.title} ',
                        "tags":[{"name":"xiio","color":"primary"},{"name":"Device","color":"danger"}]})
        props = XiioProperties.query.filter(or_(XiioProperties.title.contains(query),
                                                XiioProperties.linked_object.contains(query),
                                                XiioProperties.linked_property.contains(query),
                                                XiioProperties.linked_method.contains(query))).all()
        for prop in props:
            device = XiioDevices.get_by_id(prop.device_id)
            res.append({"url":f'xiio?op=edit&id={prop.device_id}',
                        "title":f'{device.title}->{prop.title} ({prop.linked_object}.{prop.linked_property}{prop.linked_method})',
                        "tags":[{"name":"xiio","color":"primary"},{"name":"Property","color":"warning"}]})
        return res

    def widget(self):
        with session_scope() as session:
            devs = session.query(XiioDevices).all()
            props = session.query(XiioProperties).all()
            content = {}
            offline = 0
            for dev in devs:
                av = [av for av in props if (av.device_id == dev.id and av.property_name == 'online' and av.value == '0')]
                if av:
                    offline += 1
            content['offline'] = offline
            content['count'] = len(devs)

        return render_template("widget_xiio.html",**content)
