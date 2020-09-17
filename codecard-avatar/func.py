import io
import os
import stat
import json
import logging
import requests
import shutil
import oci.object_storage
import subprocess

from subprocess import Popen
from fdk import response

# general configuration..
logging.basicConfig(level=logging.INFO)

# function logic..
def handler(ctx, data: io.BytesIO=None):

   # define variables..
   request_url = None
   ctx_card = None

   if 'apex_url' in os.environ:
      apex_url = os.environ['apex_url']
   if 'oss_bucket' in os.environ:
      oss_bucket = str(os.environ['oss_bucket'] + "/o/")
   if 'image_bg_name' in os.environ:
      image_bg_name = os.environ['image_bg_name']
   if 'identicon_service' in os.environ:
      identicon_service = str(os.environ['identicon_service'] + "/")

   # parse FDK configuration data for x-codecard-id HTTP header..
   try:
      ctx_headers = ctx.Headers()
      logging.info('HTTP Headers: ' + json.dumps(ctx_headers, indent=4))
      ctx_cardID = (ctx_headers['x-codecard-id'])
      logging.info('x-codecard-id: ' + ctx_cardID)
   except Exception as ex:
      logging.info('ERROR: Missing HTTP query parameters..', ex, flush=True)
      raise

   # obtain user fistname and lastname..
   #   - retreive code card template configuration data from Code Card back-end (Apex)..
   apex_headers = {
   "X-CODECARD-ID": ctx_cardID,
   "X-CODECARD-BUTTON-LABEL": "a",
   "X-CODECARD-BUTTON-FUNCTION": "1"
   }
   req = requests.get(url = apex_url, headers = apex_headers) 
   data = req.json()
   logging.info('Apex Response: ' + json.dumps(data, indent=4))
   #   - parse the "title" field from Apex response data to get user name..
   apex_bodytext = None
   try:
      apex_title = (data['title'])
      logging.info('Code Card "title" data from Apex: ' + apex_title)
   except (Exception, ValueError) as ex:
      logging.info(str(ex), flush=True)
      logging.info("No arguments passed to the function, trying environ vars..")
   #   - split "title" as firstname and lastname..
   name_arr = apex_title.split(" ", 1)
   firstname = name_arr[0]
   lastname = name_arr[1] if len(name_arr) > 1 else ""
   #   - shorten names for identicon generation..
   firstname_sml = firstname[0:2]
   lastname_sml = lastname[0:2] if len(name_arr) > 1 else ""

   # generate identicon..
   #   - build request string..
   image_identicon_name = firstname_sml + lastname_sml
   image_identicon_url = identicon_service + image_identicon_name + "?s=8&p=30"
   logging.info('image_identicon_name: ' + image_identicon_name)
   #   - submit rquest and save stream as .png..
   r = requests.get(image_identicon_url, stream = True)
   if r.status_code == 200:
      r.raw.decode_content = True
      with open("/tmp/" + image_identicon_name + ".png",'wb') as f:
         shutil.copyfileobj(r.raw, f)
      logging.info('Identicon sucessfully downloaded: ' + image_identicon_name + ".png")
   else:
      logging.info('Identicon Couldn\'t be retreived')

   # retrieve image background template from OSS..
   #   - build request string..
   image_bg_url = oss_bucket + image_bg_name + ".bmp"
   #   - submit request and save stream as .bmp..
   custom_image_bg_name = ("DevComm_BG_" + image_identicon_name)
   r = requests.get(image_bg_url, stream = True)
   if r.status_code == 200:
      r.raw.decode_content = True
      with open("/tmp/" + custom_image_bg_name + ".bmp",'wb') as f:
         shutil.copyfileobj(r.raw, f)
      logging.info('Background image sucessfully downloaded as: ' + custom_image_bg_name + ".bmp")
   else:
      print('Background image Couldn\'t be retreived')

   # construct personalised bitmap..
   #   - refactor identicon (resize, add border, monochrome)..
   exec_count = 1
   exec_command = ("convert /tmp/" + image_identicon_name + ".png -bordercolor Black -border 5 -resize 85x85 -monochrome -type bilevel /tmp/" + image_identicon_name + "_1.bmp")
   shell_exec(exec_command, exec_count)
   #   - merge identicon with background image..
   exec_count = 2
   exec_command = ("composite -geometry +163+75 /tmp/" + image_identicon_name + "_1.bmp /tmp/" + custom_image_bg_name + ".bmp /tmp/" + custom_image_bg_name + ".bmp")
   shell_exec(exec_command, exec_count)
   #   - text operations..
   exec_count = 3
   exec_command = ("convert /tmp/" + custom_image_bg_name + ".bmp -font Open-Sans-Bold -pointsize 20 -gravity southwest -draw \"text 7,30 '" + firstname + "'\" /tmp/" + custom_image_bg_name + "_1.bmp")
   shell_exec(exec_command, exec_count)
   exec_count = 4
   exec_command = ("convert /tmp/" + custom_image_bg_name + "_1.bmp -font Open-Sans-Bold -pointsize 20 -gravity southwest -draw \"text 7,7 '" + lastname + "'\" /tmp/" + custom_image_bg_name + "_2.bmp")
   shell_exec(exec_command, exec_count)
   exec_count = 5
   exec_command = ("convert /tmp/" + custom_image_bg_name + "_2.bmp -font Open-Sans-Bold -pointsize 11.5 -gravity southeast -draw \"text 14,5 '" + image_identicon_name + "?s=8&p=30'\" /tmp/" + custom_image_bg_name + "_3.bmp")
   shell_exec(exec_command, exec_count)
   exec_count = 6
   exec_command = ("convert /tmp/" + custom_image_bg_name + "_3.bmp -font Open-Sans-Bold -pointsize 11.5 -gravity center -annotate 90x90+120+17 \".appspot.com\" /tmp/" + custom_image_bg_name + "_4.bmp")
   shell_exec(exec_command, exec_count)
   exec_count = 7
   exec_command = ("convert /tmp/" + custom_image_bg_name + "_4.bmp -font Open-Sans-Bold -pointsize 11.5 -gravity center -draw \"text 77,-16 '..//identicon-1132'\" /tmp/" + custom_image_bg_name + "_5.bmp")
   shell_exec(exec_command, exec_count)
   #   - rotate image..
   exec_count = 8
   exec_command = ("convert /tmp/" + custom_image_bg_name + "_5.bmp -rotate -90 -type truecolor /tmp/" + custom_image_bg_name + "_6.bmp")
   shell_exec(exec_command, exec_count)

   # upload image to object storage bucket..
   bucketName = "codecard"
   objectName = custom_image_bg_name + ".bmp"
   badge = "/tmp/" + custom_image_bg_name + "_6.bmp"

   with open(badge, 'rb') as content:
      resp = put_object(bucketName, objectName, content)

   # configure response data..
   data["backgroundImage"] = oss_bucket + custom_image_bg_name + ".bmp"
   data["template"] = "template8"

   # return response data..
   return response.Response(
      ctx, response_data=json.dumps(data),
      headers={"Content-Type": "application/json"}
   )

# functions..
def put_object(bucketName, objectName, content):
   """
   put_object
   object storage service file upload..
   """
   signer = oci.auth.signers.get_resource_principals_signer()
   client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
   namespace = client.get_namespace().data
   output=""
   try:
      object = client.put_object(namespace, bucketName, objectName, content)
      output = "Success: Put object '" + objectName + "' in bucket '" + bucketName + "'"
   except Exception as e:
      output = "Failed: " + str(e.message)
   
   return { "state": output }

def shell_exec(exec_command, exec_count):
   """
   shell_exec
   invoke the shell to run a local command..
   """
   p_response = Popen([exec_command],
                    shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
                   )
   output, errors = p_response.communicate()
   logging.info("Popen Output " + str(exec_count) + ": " + output)
   logging.info("Popen Errors " + str(exec_count) + ": " + errors)

   return
