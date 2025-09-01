
import re
import os
import json
import copy



plgin_dir="dist"
def remove_dollar(text):
        pattern = re.compile(r'''
        (["'])              
        (                  
        \$               
        (?:                
            \\.              
            |                
            (?!\1).         
        )*                 
        )
        \1                
        ''', re.VERBOSE)

        def replacer(match):
            content = match.group(2)[1:].strip()  
            try:
                unescaped = bytes(content, "utf-8").decode("utf-8")
            except Exception:
                unescaped = content
            return unescaped

        return pattern.sub(replacer, text)

def extract_block(text, start_keyword='parameters: {'):
    stid=text.find("var version =")
    if stid != -1:
        text=text[stid:]
    else:
        text=text
    start_idx = text.find(start_keyword)
    if start_idx == -1:
        return None
    brace_start = text.find('{', start_idx)
    if brace_start == -1:
        return None
    count = 1
    i = brace_start + 1
    while i < len(text):
        if text[i] == '{':
            count += 1
        elif text[i] == '}':
            count -= 1
            if count == 0:
                return text[brace_start+1:i] 
        i += 1
    return None

def extract_parameters_dict(block_text):
    i = 0
    block_text= re.sub(r'//[\s\S]*?\n', '', block_text)
    length = len(block_text)
    results = []
    
    while i < length:
        match = re.match(r'\s*(\w+)\s*:', block_text[i:])
        if match:
            key = match.group(1)
            i += match.end()

            while i < length and block_text[i] in ' \t\n':
                i += 1

            if block_text[i] == '{':
                brace_start = i
                i += 1
                count = 1
                while i < length and count > 0:
                    if block_text[i] == '{':
                        count += 1
                    elif block_text[i] == '}':
                        count -= 1
                    i += 1
                block = block_text[brace_start+1:i-1]
                results.append((key, block, True)) 
            else:
                value_start = i
                in_Q=[0,0]
                in_q=[False,False,False]
                while i < length:
                    if  block_text[i] in '\n' and not any(in_Q) and not any(in_q):
                        break
                    if block_text[i]=="[":
                        in_Q[0]+=1
                    elif block_text[i]=="]":
                        in_Q[0]-=1
                    if block_text[i]=="{":
                        in_Q[1]+=1
                    elif block_text[i]=="}":
                        in_Q[1]-=1
                    elif block_text[i]=="\"":
                        in_q[0]= not in_q[0]
                    elif block_text[i]=="`":
                        in_q[1]= not in_q[1]
                    elif block_text[i]=="'":
                        in_q[2]= not in_q[2]
                   
                    i += 1
                value = block_text[value_start:i].strip()
                if value.endswith(","):
                    value=value[:-1]
                value=value.strip()
                results.append((key, value, False))
        else:
            i += 1
    return results

def parse_block_recursively(block_text):
    result = {}
    fields = extract_parameters_dict(block_text)
    for key, value, is_obj in fields:
        if is_obj:
            result[key] = parse_block_recursively(value)
        else:
            result[key] = value
    return result

def parse_all_parameters(js_code,start_keyword):
    parameters_block = extract_block(js_code, start_keyword)
    if not parameters_block:
        return {}

    raw_params = extract_parameters_dict(parameters_block)
    structured = {}

    for name, block, is_obj in raw_params:
        entry = {}
        if is_obj:
            inner = parse_block_recursively(block)
            entry.update(inner)
        else:
            entry['value'] = block
        structured[name]=entry

    return structured

def trans_param_python(param):
    param["type"]=param["type"].replace("jspsych.ParameterType.","").lower()
    param["value"]=None
    
    param["undefined"]=False
    if "default" in param:
        if param["default"]=="undefined":
            param["default"]=None
        elif param["default"]=="null":
            param["default"]=None
        elif param["default"]=="true":
            param["default"]=True
        elif param["default"]=="false":
            param["default"]=False
        if ('int' in param["type"] or 'key' in param["type"] or 'html_string' in param["type"]  or 'float' in param["type"] ) and param["default"] and param["default"]!="void 0":
            if param["default"].startswith("`"):
                #print( param["default"])
                param["default"]=f'"""{param["default"][1:-1].strip()}"""'
            param["default"]=eval(param["default"])
        if type(param["default"])==str:
            if param["default"].startswith('"') and param["default"].endswith('"'):
                param["default"]=param["default"][1:-1]
            if "[" in param["default"] and 'array' in param and param["array"]=="true":
                param["default"]=eval(param["default"])
            if "function" in param["default"] and param["type"]=="function":
                param["default"]=param["default"]
            if param["default"]=="void 0":
                param["undefined"]=True
                param["default"]=None
        if param["type"] =="int":
            try:
                param["default"]=int(param["default"])
            except:
                pass
        param["value"]=param["default"]
        
    
    if "array" in param:
        if param["array"]=="true":
            param["array"]=True
            if param["value"]==None:
                param["value"]=[]
                param["default"]=[]
            
        elif param["array"]=="false":
            param["array"]=False
    else:
        param["array"]=False
    if "no_function" in param:
        if param["no_function"]=="true":
            param["no_function"]=True   
        elif param["no_function"]=="false":
            param["no_function"]=False

    if "options" in param:
        param["options"]=eval(param["options"])

    
    if 'nested' in param:
        for param_sub in param["nested"]:
            ##print(param_sub)
            if param_sub=='required':
                param["nested"][param_sub]['default']="true"
            param["nested"][param_sub]=trans_param_python(param["nested"][param_sub])
    return param

def extract_plugin_info(js_code,file_name):
    js_code = re.sub(r'/\*\*[\s\S]*?\*/', '', js_code)
    version_pattern=r'var version = "([\s\S]*?)";'
    version = re.search(version_pattern, js_code)
    try:
        version = version.group(1).strip()
    except:
        version=''

    class_name_pattern=r"var (jsPsych[\s\S]*?) ="
    class_name = re.search(class_name_pattern, js_code)
    class_name = class_name.group(1).strip()

    js_code_location=js_code.find("var version =")
    #text=js_code[js_code_location:]
    #name_pattern = r'name:\s*"([\s\S]*?)"\s*,'
    #name = re.search(name_pattern, text)
    #name = name.group(1).strip()
    name=file_name.split('plugin-')[1].split('.')[0]

    params_dict = parse_all_parameters(js_code,start_keyword='parameters: {')
    #print("-----------------name",name)
    for param in params_dict:
        #print(params_dict[param])
        params_dict[param]=trans_param_python(params_dict[param])
    
    data_dict = parse_all_parameters(js_code,start_keyword=' data: {')
    for dparam in data_dict:
        #print(data_dict[dparam])
        data_dict[dparam]=trans_param_python(data_dict[dparam])
    return {"class_name":class_name,"plugin_name":name,"params":params_dict, 'data':data_dict,"version":version}

def extract_plugin_info_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        js_code = f.read()
    return extract_plugin_info(js_code,file_path)

def extract_plugin_info_from_folder(folder_path):
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    plugin_dict={}
    for file in files:
        if "plugin" in file:
            #print(file)
            info=extract_plugin_info_from_file(file)
            info["js_file"]=file.replace("\\","/")
            plugin_dict[info["plugin_name"]]=info
    return plugin_dict


class Plugin:
    def __init__(self,class_name,plugin_name,version, params,data,js_file,name=None,exp=None):
        self.class_name=class_name
        self.plugin_name=plugin_name
        self.version=version
        self.plugin_params=params
        self.data=data
        self.js_file=js_file
        self.exp=exp
        self.web_js_file=f"https://unpkg.com/@jspsych/plugin-{plugin_name}@{version}"
        self.web_intro=f"https://www.jspsych.org/v{exp.version[0]}/plugins/{plugin_name}"
        self.common_params={
            'timeline':{"type":"object","default":'[]',"value":'[]',"array":True,"undefined":False,"common":True},
            'data':{"type":"object","default":None,"value":None,"array":False,"undefined":False,"common":True},
            'post_trial_gap':{"type":"int","default":None,"value":None,"array":False,"undefined":False,"common":True},
            'on_start':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False,"common":True},
            'on_finish':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False,"common":True},
            'on_load':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False,"common":True},
            'css_classes':{"type":"string","default":None,"value":None,"array":False,"undefined":False,"common":True},
            'save_trial_parameters':{"type":"object","default":"{}","value":"{}","array":False,"undefined":False,"common":True},
            'save_timeline_variables':{"type":"free","default":False,"value":False,"array":True,"undefined":False,"common":True},
            'record_data':{"type":"bool","default":True,"value":True,"array":False,"undefined":False,"common":True},
            'extensions':{"type":"object","default":'[]',"value":'[]',"array":True,"undefined":False,"common":True}
        }
        self.params=self.plugin_params| self.common_params
        if name:
            self.name=name
        else:
            self.name=plugin_name.replace("-","_")
    def js_source(self,plugin_source='Web'):
        source_text=""
        if plugin_source=='Local':
            source_text+=f'    <script src="{self.js_file}"></script>\n'
            if self.plugin_name=="survey":
                source_text+=f'    <link rel="stylesheet" href="{plgin_dir}/survey.min.css">\n'
        elif plugin_source=='Web':
            source_text+=f'    <script src="{self.web_js_file}"></script>\n'
            if self.plugin_name=="survey":
                source_text+=f'    <link rel="stylesheet" href="https://unpkg.com/@jspsych/plugin-survey@{self.version}/css/survey.min.css">\n'
        elif plugin_source=='NAODAO':
            source_text+=f'    <script src="https://www.naodao.com/public/experiment/libs/plugin/plugin-{self.plugin_name}.js"></script>\n'
            if self.plugin_name=="survey":
                source_text+=f'    <link rel="stylesheet" href="https://unpkg.com/@jspsych/plugin-survey@{self.version}/css/survey.min.css">\n'
        elif plugin_source=='Credamo':
            plugins_dict = {
                "preload": "plugin-preload@1.1.0.js",
                "fullscreen": "plugin-fullscreen@1.1.0.js",
                "audio-button-response": "plugin-audio-button-response@1.1.0.js",
                "audio-keyboard-response": "plugin-audio-keyboard-response@1.1.0.js",
                "audio-slider-response": "plugin-audio-slider-response@1.1.0.js",
                "html-audio-response": "plugin-html-audio-response@1.0.0.js",
                "html-button-response": "plugin-html-button-response@1.1.0.js",
                "html-keyboard-response": "plugin-html-keyboard-response@1.1.0.js",
                "html-slider-response": "plugin-html-slider-response@1.1.0.js",
                "image-button-response": "plugin-image-button-response@1.1.0.js",
                "image-keyboard-response": "plugin-image-keyboard-response@1.1.0.js",
                "image-slider-response": "plugin-image-slider-response@1.1.0.js",
                "video-button-response": "plugin-video-button-response@1.1.0.js",
                "video-keyboard-response": "plugin-video-keyboard-response@1.1.0.js",
                "video-slider-response": "plugin-video-slider-response@1.1.0.js",
            }
            if self.plugin_name in plugins_dict.keys():
                source_text+=f'    <script src="/jspsych/static/{plugins_dict[self.plugin_name]}"></script>\n'
            else:
                source_text+=f'    <script src="{self.web_js_file}"></script>\n'
            if self.plugin_name=="survey":
                source_text+=f'    <link rel="stylesheet" href="https://unpkg.com/@jspsych/plugin-survey@{self.version}/css/survey.min.css">\n'
    
        return source_text
    
    def set_params(self, params_list):
        def convert_value(val, val_type):

            if type(val)==str and val.startswith("$"):
                return val
            elif val == None:
                return None
            elif val_type == "int" and val!="":
                return int(val)
            elif val_type == "float":
                return float(val)
            elif val_type == "bool":
                return bool(val)
            elif val_type in ("function", "object"):
                return str(val)
            elif val_type == "keys":
                return str(val).split(",") if "," in str(val) else str(val)
            elif val_type == "free":
                return val
            elif val_type == "html_string":
                return str(val)
            else:
                return str(val)

        def convert_array(val, val_type):
            if type(val)==str and val.startswith("$"):
                return val
            if not isinstance(val, list):
                return convert_value(val, val_type)
            if val == None:
                return None
            if val and isinstance(val[0], list):
                for i in range(len(val)):
                    val_i=convert_array(val[i], val_type)
                    val[i]=val_i
                return val
            elif val_type == "int":
                return [int(x) if not str(x).startswith("$") else x for x in val ]
            elif val_type == "float":
                return [float(x) if not str(x).startswith("$") else x for x in val ]
            elif val_type == "bool":
                return [bool(x) if not str(x).startswith("$") else x for x in val ]
            elif val_type == "free":
                return [x for x in val]
            else:
                return [str(x) for x in val]

        for param in params_list:
            if isinstance(params_list, list):
                name = param["name"]
                val = param["val"]
            else:
                name = param
                val = params_list[param]
                if isinstance(val, dict):
                    val=val["value"]
            if name not in self.params:
                continue
            #print(name,val)
            param_def = copy.deepcopy(self.params[name])
            val_type = param_def["type"]
            is_array = param_def["array"]

            if not is_array:
                if val_type != "complex":
                    param_def["value"] = convert_array(val, val_type)
            else:
                if val_type == "complex":
                    if isinstance(params_list, list):
                        lst = val if isinstance(val, list) and all(isinstance(item, list) for item in val) else [val]
                    else:
                        lst = val if isinstance(val, list) else [val]
                    value_list = []
                    for sublist in lst:
                        nested_params = copy.deepcopy(param_def["nested"])
                        for sub in sublist:
                            if isinstance(params_list, list):
                                sub_name = sub["name"]
                                sub_val = sub["val"]
                            else:
                                sub_name = sub
                                sub_val = sublist[sub]
                                if isinstance(sub_val, dict):
                                    sub_val=sub_val["value"]
                            sub_def = nested_params[sub_name]
                            sub_type = sub_def["type"]

                            if not sub_def["array"]:
                                sub_def["value"] = convert_value(sub_val, sub_type)
                            else:
                                sub_def["value"] = convert_array(sub_val, sub_type)

                        value_list.append(nested_params)
                    param_def["value"] =  value_list
                else:
                    param_def["value"] =  convert_array(val, val_type)
            self.params[name] = param_def

    def __eq__(self, other):
        if not isinstance(other, Plugin):
            return False
        return self.class_name == other.class_name and self.plugin_name == other.plugin_name and self.version==other.version and self.params==other.params and self.js_file==other.js_file 
    
    
    
    def to_js(self,js_type='push'):
        js_json={}
        js_json["$type"]="$"+self.class_name
        for param in self.params:
            if self.params[param]["type"]!="complex":
                if self.params[param]["default"]!=self.params[param]["value"]:
                    if self.params[param]["type"] in ("function", "object"):
                        js_json["$"+param]="$"+str(self.params[param]["value"])
                    elif self.params[param]["type"] in ("html_string") :
                        js_json["$"+param]=f"$`{str(self.params[param]["value"])}`"
                    else:
                        js_json["$"+param]=self.params[param]["value"]
                elif self.params[param]["undefined"]:
                    js_json["$"+param]=self.params[param]["value"]
            else:
                if self.params[param]["value"]:
                    if len(self.params[param]["value"])!=0:
                        complex_list=[]
                        for val in self.params[param]["value"]:
                            nested_json={}
                            for nested_param in self.params[param]["nested"]:
                                if self.params[param]["nested"][nested_param]["default"]!=val[nested_param]["value"]:
                                    if self.params[param]["type"] in ("function", "object"):
                                        nested_json["$"+nested_param]="$"+str(val[nested_param]["value"])
                                    elif self.params[param]["type"] in ("html_string") :
                                        nested_json["$"+nested_param]=f"$`{str(val[nested_param]["value"])}`"
                                    else:
                                        nested_json["$"+nested_param]=val[nested_param]["value"]
                                    
                            complex_list.append(nested_json)
                        js_json["$"+param]=complex_list
        js_json_text= json.dumps(js_json, indent=8, ensure_ascii=False)
        js_json_text=remove_dollar(js_json_text)
        js_json_text=js_json_text.encode('utf-8').decode('unicode_escape')
        if js_type=='push':
            js_json_text=f"    var {self.name} = {js_json_text};\n    timeline.push({self.name});\n\n"
        else:
            js_json_text=f"    var {self.name} = {js_json_text};\n\n"
        return js_json_text

class code(Plugin):
    def __init__(self, exp, name=None):
            super(self.__class__, self).__init__(
                class_name='code',
                plugin_name='code',
                version='0.0',
                params={'code':{"type":"function","default":'',"value":'',"array":False,"undefined":False}},
                data={},
                js_file='',
                name=name,
                exp=exp
            )
            self.common_params={}
            self.params={'code':{"type":"function","default":'',"value":'',"array":False,"undefined":False}}
    def js_source(self,plugin_source='Web'):
        return ''
    def to_js(self,js_type='push'):
        #每一行前添加    
        js_code_split=self.params['code']['value'].strip().split("\n")
        js_code=""
        for line in js_code_split:
            js_code+=f"    {line.strip()}\n"
        return js_code+"\n"
    
class procedure_start(Plugin):
    def __init__(self, exp, name=None):
            super(self.__class__, self).__init__(
                class_name='procedure-start',
                plugin_name='procedure-start',
                version='0.0',
                params={'timeline_variables':{"type":"object","default":[],"value":[],"array":True,"undefined":False},
                        'randomize_order':{"type":"bool","default":False,"value":False,"array":False,"undefined":False},
                        'repetitions':{"type":"int","default":1,"value":1,"array":False,"undefined":False},
                        'sample':{"type":"object","default":{},"value":{},"array":False,"undefined":False},
                        'loop_function':{"type":"function","default":'function(){ return true; }',"value":'function(){ return true; }',"array":False,"undefined":False},
                        'conditional_function':{"type":"function","default":'function(){ return true; }',"value":'function(){ return true; }',"array":False,"undefined":False},
                        'on_timeline_start':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False},
                        'on_timeline_finish':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False},
                        },
                        
                data={},
                js_file='',
                name=name,
                exp=exp
            )

            self.common_params={}
            self.params={'timeline_variables':{"type":"object","default":[],"value":[],"array":True,"undefined":False},
                        'randomize_order':{"type":"bool","default":False,"value":False,"array":False,"undefined":False},
                        'repetitions':{"type":"int","default":1,"value":1,"array":False,"undefined":False},
                        'sample':{"type":"object","default":'{}',"value":'{}',"array":False,"undefined":False},
                        'loop_function':{"type":"function","default":'function(){ return true; }',"value":'function(){ return true; }',"array":False,"undefined":False},
                        'conditional_function':{"type":"function","default":'function(){ return true; }',"value":'function(){ return true; }',"array":False,"undefined":False},
                        'on_timeline_start':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False},
                        'on_timeline_finish':{"type":"function","default":'function(){ return; }',"value":'function(){ return; }',"array":False,"undefined":False},
                        }
            self.timeline=[]

    def js_source(self,plugin_source='Web'):
        return ''
    def to_js(self,js_type='push'):
        js_json={}
        js_json["$timeline"]=['$'+ timeline for timeline in self.timeline]
        for param in self.params:
            if self.params[param]["type"]!="complex":
                if self.params[param]["undefined"]:
                    js_json["$"+param]=self.params[param]["value"]
                else:
                    if self.params[param]["default"]!=self.params[param]["value"]:
                        if self.params[param]["type"] in ("function", "object"):
                            js_json["$"+param]="$"+str(self.params[param]["value"])
                        else:
                            js_json["$"+param]=self.params[param]["value"]
            else:
                if self.params[param]["value"]:
                    if len(self.params[param]["value"])!=0:
                        complex_list=[]
                        for val in self.params[param]["value"]:
                            nested_json={}
                            for nested_param in self.params[param]["nested"]:
                                if self.params[param]["nested"][nested_param]["default"]!=val[nested_param]["value"]:
                                    if self.params[param]["type"] in ("function", "object"):
                                        nested_json["$"+nested_param]="$"+str(val[nested_param]["value"])
                                    else:
                                        nested_json["$"+nested_param]=val[nested_param]["value"]
                                    
                            complex_list.append(nested_json)
                        js_json["$"+param]=complex_list
        
        js_json_text= json.dumps(js_json, indent=8, ensure_ascii=False)
        #print(js_json_text)
        js_json_text=remove_dollar(js_json_text)
        if js_type=='push':
            js_json_text=f"    var {self.name} = {js_json_text};\n    timeline.push({self.name});\n\n"
        else:
            js_json_text=f"    var {self.name} = {js_json_text};\n\n"
        #print(js_json_text)
        return js_json_text
    
class procedure_end(Plugin):
    def __init__(self, exp, name=None):
            super(self.__class__, self).__init__(
                class_name='procedure-end',
                plugin_name='procedure-end',
                version='0.0',
                params={'connect':{"type":"select","default":'',"value":[''],"array":False,"undefined":False}},
                data={},
                js_file='',
                name=name,
                exp=exp
            )

            self.common_params={}
            self.params={'connect':{"type":"select","default":'',"value":[''],"array":False,"undefined":False}}

    def js_source(self,plugin_source='Web'):
        return ''
    def to_js(self,js_type='push'):
        return ''


    
def registry_plugin():
    dict_info=extract_plugin_info_from_folder(plgin_dir)
    plugin_registry={}
    for class_name in dict_info:
        def __init__(self, exp, name=None, _config=dict_info[class_name]):
            super(self.__class__, self).__init__(
                class_name=_config["class_name"],
                plugin_name=_config["plugin_name"],
                version=_config["version"],
                params=_config["params"],
                data=_config["data"],
                js_file=_config["js_file"],
                name=name,
                exp=exp
            )
        subclass = type(
            class_name,
            (Plugin,),
            {"__init__": __init__}
        )
        plugin_registry[class_name] = subclass
    plugin_registry["code"] = code
    plugin_registry["procedure-start"] = procedure_start
    plugin_registry["procedure-end"] = procedure_end
    return plugin_registry

import time
    
class Expriment:
    def __init__(self,file_name,plugin_source='Web',data_save='Local',name=None,timeline_list=None,plugin_all=None,head_script=''):
        self.file_name=file_name
        self.head_script=head_script
        if name:
            self.name=name
        else:
            self.name=file_name
        self.plugin_source=plugin_source
        self.data_save=data_save
        self.timeline=[]
        self.plugin_used={}
        if plugin_all:
            self.plugin_all=plugin_all
        else:
            self.plugin_all=registry_plugin()
        self.load_version()
        self.source_load()
        time1=time.time()
        if timeline_list:
            self.import_from_json(timeline_list)
        time2=time.time()
        #print("import time:",time2-time1)
        
        

    def import_from_json(self, timeline_list):
        start_time = time.time()  # 记录函数开始时间
        step_times = {
            "extract_name_type": 0,
            "check_plugin_used": 0,
            "create_plugin_instance": 0,
            "set_params": 0,
            "deepcopy_plugin": 0,
            "append_timeline": 0,
        }

        for plugin_setting in timeline_list:

            # 提取 plugin_name 和 plugin_type
            if "name" in plugin_setting:
                plugin_name = plugin_setting["name"]
            else:
                plugin_name = plugin_setting["params"]["name"]

            if "type" in plugin_setting:
                plugin_type = plugin_setting["type"]
            else:
                plugin_type = plugin_setting["params"]["type"]

            if "params" in plugin_setting:
                plugin_params = plugin_setting["params"]
            else:
                plugin_params = plugin_setting
            # 检查 plugin_name 是否在 self.plugin_used 中
            if plugin_name not in self.plugin_used:

                # 创建插件实例
                plugin= self.plugin_all[plugin_type](self, plugin_name)

                # 设置参数
                plugin.set_params(plugin_params)

                self.plugin_used[plugin_name] = plugin

                self.timeline.append(plugin_name)
            else:
                # 如果插件已存在，仅添加到 timeline
                self.timeline.append(plugin_name)


            

    def source_load(self):
        self.js_source=f"{plgin_dir}/jspsych.js"
        self.css_source=f"{plgin_dir}/jspsych.css"
        self.js_web_source=f"https://unpkg.com/jspsych@{self.version}"
        self.css_web_source=f"https://unpkg.com/jspsych@{self.version}/css/jspsych.css"  
    
    def load_version(self):
        with open(f"{plgin_dir}/jspsych.js", 'r', encoding='utf-8') as f:
            js_code = f.read()
        version_pattern=r'var version = "([\s\S]*?)";'
        version = re.search(version_pattern, js_code)
        self.version = version.group(1).strip()

    def add_plugin_to_timeline(self,plugin,i=None):
        if plugin.name in self.plugin_used.keys():
            if plugin==self.plugin_used[plugin.name]:
                pass
            else:   
                self.plugin_used[plugin.name]=plugin
        else:
            self.plugin_used[plugin.name]=plugin
        if i:
            self.timeline.insert(i, plugin.name)
        else:
            self.timeline.append(plugin.name)
    def delete_plugin_from_timeline(self,i):
        if len(self.timeline)>i:
            del self.timeline[i]
    def delete_plugin_from_used(self,name):
        if name in self.plugin_used:
            del self.plugin_used[name]

    def timeline_to_js(self):
        plugin_define=""
        plugin_source=""
        plugin_source_added=[]
        in_procedure=[]
        for plugin in self.timeline:
            if self.plugin_used[plugin].class_name=='procedure-start':
                in_procedure.append(plugin)
                continue

            if len(in_procedure)>0:
                if self.plugin_used[plugin].class_name=='procedure-end':
                    connect=self.plugin_used[plugin].params['connect']['value']
                    in_procedure=[i  for i in in_procedure if i!= connect]
                    if len(in_procedure)==0:
                        plugin_define+=self.plugin_used[connect].to_js(js_type='push')
                    else:
                        plugin_define+=self.plugin_used[connect].to_js(js_type='define')
                        self.plugin_used[in_procedure[-1]].timeline.append(connect)
                    continue
                
                plugin_define+=self.plugin_used[plugin].to_js(js_type='define')
                self.plugin_used[in_procedure[-1]].timeline.append(plugin)
            else:
                plugin_define+=self.plugin_used[plugin].to_js(js_type='push')

            if self.plugin_used[plugin].plugin_name not in plugin_source_added:
                plugin_source+=self.plugin_used[plugin].js_source(self.plugin_source)
                plugin_source_added.append(self.plugin_used[plugin].plugin_name)
 
        if len(in_procedure)>0:
            for i in range(len(in_procedure)):
                if i==len(in_procedure)-1:
                    plugin_define+=self.plugin_used[in_procedure[len(in_procedure)-i-1]].to_js(js_type='push')
                else:
                    plugin_define+=self.plugin_used[in_procedure[len(in_procedure)-i-1]].to_js(js_type='define')
                    self.plugin_used[in_procedure[len(in_procedure)-i-1-1]].timeline.append(in_procedure[len(in_procedure)-i-1])
        return plugin_source,plugin_define
    def to_js(self, plugin_source_type, data_save_type):
        template="""
<!DOCTYPE html>
<html>
  <head>
    <title>[[[[name]]]]</title>
    <script src="[[[[js_source]]]]"></script>
[[[[plugin_source]]]]    <link href="[[[[css_source]]]]" rel="stylesheet" type="text/css" />
[[[[head_script]]]]
  </head>
  <body></body>
  <script>

    /* initialize jsPsych */
    var jsPsych = initJsPsych([[[[on_finish]]]]);

    /* create timeline */
    var timeline = [];

[[[[plugin_define]]]]

    /* start the experiment */
    jsPsych.run(timeline);

  </script>
</html>
"""
        template=template.replace('[[[[name]]]]',self.name)

        if plugin_source_type=='Local':
            template=template.replace('[[[[js_source]]]]',self.js_source)
            template=template.replace('[[[[css_source]]]]',self.css_source)
        elif plugin_source_type=='Web':
            template=template.replace('[[[[js_source]]]]',self.js_web_source)
            template=template.replace('[[[[css_source]]]]',self.css_web_source)
        elif plugin_source_type=='Credamo':
            template=template.replace('[[[[js_source]]]]','/jspsych/static/jspsych@7.1.2.js')
            template=template.replace('[[[[css_source]]]]','/jspsych/static/jspsych.css')
        elif plugin_source_type=='NAODAO':
            template=template.replace('[[[[js_source]]]]','https://www.naodao.com/public/experiment/libs/jspsych-7/jspsych.js')
            template=template.replace('[[[[css_source]]]]','https://www.naodao.com/public/experiment/libs/jspsych-7/css/jspsych.css')

        head_script=self.head_script
        if  data_save_type=='Display':
            template=template.replace('[[[[on_finish]]]]',"{on_finish: function() {jsPsych.data.displayData();}}")
            
        elif data_save_type=='Local':
            template=template.replace('[[[[on_finish]]]]',"{on_finish: function() {jsPsych.data.get().localSave('csv',jsPsych.randomization.randomID(6)+'_data.csv');}}")

        elif data_save_type=='NAODAO':
            head_script=head_script+'\n<script src="https://www.naodao.com/public/experiment/libs/extension/naodao-2021-12.js"></script>'
            template=template.replace('[[[[on_finish]]]]',"{extensions: [{type: Naodao}]}")

        elif data_save_type=='Credamo':
            head_script=head_script+'\n<script src="/jspsych/static/credamo-jspsych.min.js"></script>'
            template=template.replace('[[[[on_finish]]]]',"{on_finish: function() {onCredamoEndTrialFinish(jsPsych.data.get().csv());}}")

        elif data_save_type=='JATOS':
            head_script=head_script+'\n    <script src="jatos.js"></script>'
            template=template.replace('[[[[on_finish]]]]',"{on_finish: () => jatos.startNextComponent(jsPsych.data.get().json())}")
            template=template.replace('jsPsych.run(timeline);',"""jatos.onLoad(() => {
        jsPsych.run(timeline);
    });""")
        
        elif data_save_type=='Local_Server':
            template=template.replace('[[[[on_finish]]]]',"""{on_finish: async function sendCsvToBackend() {
        const csvData =jsPsych.data.get().csv() ;
        const url = '/receive-csv/';
        const response = await fetch(url, {
          method: 'POST',                  
          headers: {
            'Content-Type': 'text/plain',         
          },
          body: csvData                    
        });
        const result = await response.json();
        document.write("<p>End</p>")
      }}""")
        
        head_script_split=head_script.strip().split("\n")
        head_script=""
        for line in head_script_split:
            head_script+=f"    {line.strip()}\n"
        template=template.replace('[[[[head_script]]]]',head_script)
        plugin_source,plugin_define=self.timeline_to_js()

        if data_save_type=='NAODAO':
            save_plugin=self.plugin_all['html-keyboard-response'](self,name='naodao_save_date')
            save_plugin.params['trial_duration']['value']=100
            save_plugin.params['stimulus']['value']='Save date...'
            save_plugin.params['extensions']['value']='[{type: Naodao}]'
            plugin_define+=save_plugin.to_js()
            if 'html-keyboard-response' not in plugin_source:
                plugin_source+=save_plugin.js_source(self.plugin_source)
        template=template.replace('[[[[plugin_source]]]]',plugin_source)
        template=template.replace('[[[[plugin_define]]]]',plugin_define)

        return template 
    def preview(self):
        return self.to_js('Web','Display')
    def export(self):
        return self.to_js(self.plugin_source,self.data_save)


if __name__=="__main__":
    plugin_registry=registry_plugin()
    


    params_list=[{"name":"save_timeline_variables","val":True},{"name":"questions","val":[{"name":"prompt","val":"I like vegetables."},{"name":"labels","val":[
            "Strongly Disagree", 
            "Disagree", 
            "Neutral", 
            "Agree", 
            "Strongly Agree"
        ]}]}]
    
    params_list=[{"name":"ass","type":"survey-likert","params":{"save_timeline_variables":True,"questions":[{"prompt":"I like vegetables.","labels":[
            "Strongly Disagree", 
            "Disagree", 
            "Neutral", 
            "Agree", 
            "Strongly Agree"
        ]}]}}]
    exp=Expriment("HHH",True,timeline_list=params_list)
    exp.open_in_web()

