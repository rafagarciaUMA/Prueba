import sys
sys.path.append('.')
from libs.osm_nbi_util import NbiUtil as osmUtils
from libs.openstack_util import OSUtils as osUtils
from flask import Flask, jsonify, request
from flask_restful import Resource, Api
import json
import yaml
import requests
from pymongo import MongoClient

from gevent.pywsgi import WSGIServer
import logging

from flask_cors import CORS



app = Flask(__name__)
api = Api(app)
CORS(app)

# Logging Parameters
logger = logging.getLogger("-MANO API-")
fh = logging.FileHandler('mano.log')

stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s')
stream_formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s')
fh.setFormatter(formatter)
stream_handler.setFormatter(stream_formatter)
logger.setLevel(logging.DEBUG)
logger.addHandler(fh)
logger.addHandler(stream_handler)



def reachable_interface(interface):
    """
    interface example:
    {
        "ns-vld-id": "public_vld",
        "ip-address": "192.168.100.101",
        "mac-address": "fa:16:3e:f6:11:7e",
        "name": "haproxy_vdu_eth1"
    }
    """
    import os
    ret = os.system("ping -n 3 {0}".format(interface["ip-address"]))
    if ret == 0:
        return True
    return False

def create_prometheus_target(ip="192.168.32.10", env="prod", target="localhost", port="9100", job="node",
                             service="test-service", service_id="T3SDavkl3pall9688g"):

    obj =\
        {
            "targets": ["{0}:{1}".format(target, port)],
            "labels": {
                "env": env,
                "job": job,
                "group": job,
                "service": service,
                "service_id": service_id
            }
        }
    print(obj)
    url = "http://{0}:5001/target".format(ip)
    headers = {"Accept": "application/json"}
    try:
        response = requests.post(url,
                                 headers=headers,
                                 verify=False,
                                 json=obj)
    except Exception as e:
        return {"error": str(e), "status": response.status_code}, response.status_code
    return json.loads(response.text), response.status_code


def send_prometheus_targets(ns_report):
    logger.info("Sending target to Prometheus to monitor the VDUs")
    for vdu in ns_report["interfaces"]:
        for interface in vdu["interfaces"]:
            if reachable_interface(interface):
                print("Interface {0} reachable: job: {1}, service: {2}, id: {3}".format(interface['ip-address'], interface["name"], ns_report["NS_name"], ns_report["NS_ID"]))
                create_prometheus_target(target=interface["ip-address"], job=interface["name"], service=ns_report["NS_name"], service_id=ns_report["NS_ID"])



class InstantiateNSD(Resource):
    def post(self, nsd_id):
        logger.info("Instantiating NSD: {}".format(nsd_id))
        response, status_code = nbiUtil.instantiate_by_nsd_id(nsd_id)
        # if the instantiation has been successful, we create the targets for monitoring the VDUs
        if status_code in [200, 201]:
            send_prometheus_targets(response)
        # TODO: hacer un rollback del servicio desplegado si no se ha completado todo el proceso
        return response, status_code


class NS_interfaces(Resource):
    def get(self, ns_id):
        logger.info("Retrieving interfaces for NS instance {}".format(ns_id))
        return nbiUtil.get_ns_interfaces_by_ns_id(ns_id)



class Prometheus(Resource):
    def post(self):
        input = request.get_json()
        print(str(request.remote_addr))
        return input


class VNFD_get(Resource):
    def get(self, vnf_name):
        logger.info("Retrieving VNFD: {}".format(vnf_name))
        return nbiUtil.get_vnfd_by_name(vnf_name)

    def delete(self, vnf_name):
        logger.info("Deleting VNFD: {}".format(vnf_name))
        return nbiUtil.delete_vnfd(vnf_name)


class VNFD(Resource):
    def validate(self, file):
        import tarfile
        import shutil

        logger.info("Validating VNFD {}".format(file))
        if file.endswith("tar.gz"):
            # unzip the package
            tar = tarfile.open(file, "r:gz")
            folder = tar.getnames()[0]
            tar.extractall()
            tar.close()
            # Delete the folder we just created
            shutil.rmtree(folder, ignore_errors=True)
            return True
        logger.info("Invalid VNFD")
        return False

    def post(self):
        import os

        try:
            file = request.files.get("vnfd")
            if not file:
                logger.error("VNFD file not present in the query")
                return "VNFD file not present in the query", 404
            print(file)
            # Write package file to static directory and validate it
            file.save(file.filename)
            if self.validate(file.filename):
                r, status_code = nbiUtil.upload_vnfd_package(file)
                os.remove(file.filename)
                return json.loads(r), status_code
            # Delete package file when done with validation
            os.remove(file.filename)
            return "File not valid", 406
        except Exception as e:
            return {"error": str(e), "status": type(e).__name__}
        


    def get(self):
        logger.info("Retrieving available VNFDs")
        res, code = nbiUtil.get_onboarded_vnfds()
        if res:
            logger.debug("VNFD list: {}".format(res))
        else:
            logger.error("Failed to retrieve VNFD list")
        return res, code


class NSD_get(Resource):
    def get(self, ns_name):
        logger.info("Retrieving NSD: {}".format(ns_name))
        res, code = nbiUtil.get_nsd_by_name(ns_name)
        if res:
            logger.debug("NSD: {}".format(res))
        else:
            logger.error("Failed to retrieve NSD")
        return res, code
        

    def delete(self, ns_name):
        logger.info("Deleting NSD: {}".format(ns_name))
        res, code = nbiUtil.delete_nsd(ns_name)
        if code is 204:
            logger.debug("NSD successfully deleted")
        else:
            logger.debug("NSD cannot be deleted: {} - {}".format(res, code))
        return res, code

class NSD_post(Resource):
    def validate(self, file):
        import tarfile
        import shutil

        logger.info("Validating NSD file")
        if file.endswith("tar.gz"):
            # unzip the package
            tar = tarfile.open(file, "r:gz")
            logger.info("Unpacking file for validation")
            folder = tar.getnames()[0]
            tar.extractall()
            tar.close()
            # Delete the folder we just created
            shutil.rmtree(folder, ignore_errors=True)
            logger.info("Deleting temporary files")
            return True
        logger.error("NSD file format invalid: it should be .tar.gz")
        return False

    def post(self):
        import os

        try:
            logger.info("Uploading NSD")
            file = request.files.get("nsd")
            if not file:
                logger.error("NSD file not present in the query. Example: curl -X POST -F \"nsd=@<file path>\" http://<server IP>:5000/nsd")
                return "NSD file not present in the query", 404
            # Write package file to static directory and validate it
            file.save(file.filename)
            if self.validate(file.filename):
                r, status_code = nbiUtil.upload_nsd_package(file)
                print(status_code)
                os.remove(file.filename)
                return json.loads(r), status_code
            # Delete package file when done with validation
            os.remove(file.filename)
            return "File not valid", 406
        except Exception as e:
            return {"error": str(e), "status": type(e).__name__}


    def get(self):
        logger.info("Retrieving available NSDs")
        res, code = nbiUtil.get_onboarded_nsds()
        logger.debug(res)
        return res, code


class VIM_image_post(Resource):
    def post(self):
        import os
        
        try:
            logger.info("Uploading image")
            file = request.files.get("image")
            if not file:
                logger.error("Image file not present in the query. Example: curl -X POST -F \"image=@<file path>\" <URL>")
                return "Image file not present in the query", 404
            # Save file to static directory and validate it
            file.save(file.filename)

            # get image parameters
            disk_format = request.args.get('disk_format')
            container_format = request.args.get('container_format')

            r = osUtils.upload_image(vim_conn, file, disk_format, container_format)
            # Delete file when done with validation
            os.remove(file.filename)
        except Exception as e:
            return {"error": str(e), "status": type(e).__name__}
        #osUtils.list_images(vim_conn) 
        return "Image status: {}".format(r.status), 201



#api.add_resource(InstantiateNSD, '/instantiate_nsd/<string:nsd_id>')
#api.add_resource(NS_interfaces, '/get_interfaces/<string:ns_id>')
api.add_resource(VNFD_get, '/vnfd/<string:vnf_name>')
api.add_resource(VNFD, '/vnfd')
api.add_resource(NSD_post, '/nsd')
api.add_resource(NSD_get, '/nsd/<string:ns_name>')
api.add_resource(VIM_image_post, '/image')

api.add_resource(Prometheus, '/prometheus')


if __name__ == '__main__':
    import configparser
    config_file = 'mano.conf'

    # load the NFVO parameters from the config file
    try:
        config = configparser.ConfigParser()
        config.read(config_file)
        #NFVO config
        nfvo_type = str(config['NFVO']['TYPE'])
        nfvo_ip = str(config['NFVO']['IP'])
        nfvo_user = str(config['NFVO']['USER'])
        nfvo_pass = str(config['NFVO']['PASSWORD'])
        nfvo_vim_account = str(config['NFVO']['VIM_ACCOUNT'])
        #VIM config
        vim_type = str(config['VIM']['TYPE'])
        vim_auth_url = str(config['VIM']['AUTH_URL'])
        vim_user = str(config['VIM']['USER'])
        vim_pass = str(config['VIM']['PASSWORD'])
        vim_project = str(config['VIM']['PROJECT'])

        logger.info("Starting app")
        # init the NFVO
        logger.info("Adding NFVO- Type: {}, IP:{}, User:{}, VIM account:{}".format(nfvo_type, nfvo_ip, nfvo_user, nfvo_vim_account))
        if nfvo_type == "OSM":
            nbiUtil = osmUtils(osm_ip=nfvo_ip, username=nfvo_user, password=nfvo_pass, vim_account_id=nfvo_vim_account)
        else:
            logger.error("NFVO type {} not supported".format(nfvo_type))
            raise KeyError("NFVO type {} not supported".format(nfvo_type))
        # init the VIM
        logger.info("Adding VIM- Type: {}, Auth URL:{}, User:{}, Project:{}".format(vim_type, vim_auth_url, vim_user, vim_project))
        if vim_type == "openstack":
            vim_conn = osUtils.connection(auth_url=vim_auth_url, region="RegionOne", project_name=vim_project, username=vim_user, password=vim_pass)
        else:
            logger.error("VIM type {} not supported".format(vim_type))
            raise KeyError("VIM type {} not supported".format(vim_type))
        #app.run(host='0.0.0.0', debug=True)
        http_server = WSGIServer(('', 5001), app)
        http_server.serve_forever()
    except KeyError as ex:
        logger.error("Config file {} badly formed: {}".format (config_file, ex.args))
    except Exception as ex:
        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
        message = template.format(type(ex).__name__, ex.args)
        logger.error(message)
