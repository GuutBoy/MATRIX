import os
import sys
from os.path import expanduser

import boto3
import botocore
import json
import time
from datetime import datetime
from collections import OrderedDict
from botocore import exceptions


config_file_path = sys.argv[1]
task_idx = sys.argv[2]


def create_key_pair():
    with open(config_file_path) as regions_file:
        data = json.load(regions_file, object_pairs_hook=OrderedDict)
        regions = list(data['regions'].values())

    for idx in range(len(regions)):
        client = boto3.client('ec2', region_name=regions[idx][:-1])
        try:
            key_pair = client.create_key_pair(KeyName='Matrix%s' % regions[idx].replace('-', ''))
            print(key_pair.KeyMaterial)
        except botocore.exceptions.EndpointConnectionError as e:
            print(e.response['Error']['Message'])
        except botocore.exceptions.ClientError as e:
            print(e.response['Error']['Message'])


def create_security_group():
    with open(config_file_path) as regions_file:
        data = json.load(regions_file, object_pairs_hook=OrderedDict)
        regions = list(data['regions'].values())

    for idx in range(len(regions)):
        client = boto3.client('ec2', region_name=regions[idx][:-1])
        # create security group
        try:
            response = client.create_security_group(
                Description='Matrix system security group',
                GroupName='MatrixSG%s' % regions[idx].replace('-', '')[:-1],
                DryRun=False
            )

            # Add FW rules
            sg_id = response['GroupId']
            ec2 = boto3.resource('ec2', region_name=regions[idx][:-1])
            security_group = ec2.SecurityGroup(sg_id)
            security_group.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=0, ToPort=65535)
        except botocore.exceptions.EndpointConnectionError as e:
            print(e.response['Error']['Message'])
        except botocore.exceptions.ClientError as e:
            print(e.response['Error']['Message'])


def check_latest_price(instance_type, region):
    client = boto3.client('ec2', region_name=region[:-1])
    prices = client.describe_spot_price_history(InstanceTypes=[instance_type], MaxResults=1,
                                                ProductDescriptions=['Linux/UNIX (Amazon VPC)'],
                                                AvailabilityZone=region)
    return prices['SpotPriceHistory'][0]['SpotPrice']


def deploy_instances():
    with open(config_file_path) as data_file:
        data = json.load(data_file, object_pairs_hook=OrderedDict)
        machine_type = data['aWSInstType']
        price_bids = data['aWWSBidPrice']
        number_of_parties = list(data['numOfParties'].values())
        amis_id = list(data['amis'].values())
        regions = list(data['regions'].values())

    if len(regions) > 1:
        number_of_instances = max(number_of_parties) // len(regions)
    else:
        number_of_instances = max(number_of_parties)

    date = datetime.now().replace(hour=datetime.now().hour - 3)
    print('Current date : \n%s' % str(date))
    new_date = date.replace(hour=date.hour + 6)

    for idx in range(len(regions)):
        client = boto3.client('ec2', region_name=regions[idx][:-1])

        print('Deploying instances :\nregion : %s\nnumber of instances : %s\nami_id : %s\ninstance_type : %s\n'
              'valid until : %s' % (regions[idx], number_of_instances, amis_id[idx], machine_type, str(new_date)))

        number_of_instances_to_deploy = check_running_instances()

        number_of_instances_to_deploy = number_of_instances - number_of_instances_to_deploy

        if number_of_instances_to_deploy > 0:
            # check if price isn't too low
            winning_bid_price = check_latest_price(machine_type, regions[idx])
            if float(price_bids) < float(winning_bid_price):
                price_bids = str(winning_bid_price)

            client.request_spot_instances(
                    DryRun=False,
                    SpotPrice=price_bids,
                    InstanceCount=number_of_instances_to_deploy,
                    ValidUntil=new_date,
                    LaunchSpecification=
                    {
                        'ImageId': amis_id[idx],
                        'KeyName': 'Matrix%s' % regions[idx].replace('-', '')[:-1],
                        'SecurityGroups': ['MatrixSG%s' % regions[idx].replace('-', '')[:-1]],
                        'InstanceType': machine_type,
                        'Placement':
                            {
                                'AvailabilityZone': regions[idx],
                            },
                    }
            )

            time.sleep(240)
            get_network_details(regions)

    print('Finished to deploy machines')
    sys.stdout.flush()


def get_network_details(regions):
    with open(config_file_path) as data_file:
        data = json.load(data_file)
        protocol_name = data['protocol']
        os.system('mkdir -p ../%s' % protocol_name)

    instances_ids = list()
    public_ip_address = list()

    if len(regions) == 1:
        private_ip_address = list()

    number_of_parties = max(list(data['numOfParties'].values()))
    if 'local' in regions:
        with open('parties.conf', 'w+') as private_ip_file:
            for ip_idx in range(len(number_of_parties)):
                private_ip_file.write('party_%s_ip=127.0.0.1\n' % ip_idx)
                public_ip_address.append('127.0.0.1')

            port_counter = 8000
            for ip_idx in range(len(number_of_parties)):
                private_ip_file.write('party_%s_port=%s\n' % (ip_idx, port_counter))
                port_counter += 100

    elif 'servers' in regions:
        server_file = input('Enter your server file configuration: ')
        os.system('mv %s public_ips' % server_file)

        server_ips = []
        with open('public_ips', 'r+') as server_ips_file:
            for line in server_ips_file:
                server_ips.append(line)

            with open('parties.conf', 'w+') as private_ip_file:
                for ip_idx in range(len(server_ips)):
                    print('party_%s_ip=%s' % (ip_idx, server_ips[ip_idx]))
                    private_ip_file.write('party_%s_ip=127.0.0.1' % ip_idx)

                port_counter = 8000
                for ip_idx in range(len(server_ips)):
                    private_ip_file.write('party_%s_port=%s\n' % (ip_idx, port_counter))

    else:
        for idx in range(len(regions)):
            client = boto3.client('ec2', region_name=regions[idx][:-1])
            response = client.describe_spot_instance_requests()

            for req_idx in range(len(response['SpotInstanceRequests'])):
                if response['SpotInstanceRequests'][req_idx]['State'] == 'active' or \
                                response['SpotInstanceRequests'][req_idx]['State'] == 'open':
                    instances_ids.append(response['SpotInstanceRequests'][req_idx]['InstanceId'])

            # save instance_ids for experiment termination
            with open('instances_ids', 'a+') as ids_file:
                for instance_idx in range(len(instances_ids)):
                    ids_file.write('%s\n' % instances_ids[instance_idx])

                ec2 = boto3.resource('ec2', region_name=regions[idx][:-1])
                instances = ec2.instances.filter(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])

                for inst in instances:
                    if inst.id in instances_ids:
                        public_ip_address.append(inst.public_ip_address)
                        if len(regions) == 1:
                            private_ip_address.append(inst.private_ip_address)

            print('Parties network configuration')
            with open('parties.conf', 'w+') as private_ip_file:
                if len(regions) > 1:
                    for private_idx in range(len(public_ip_address)):
                        print('party_%s_ip=%s' % (private_idx, public_ip_address[private_idx]))
                        private_ip_file.write('party_%s_ip=%s\n' % (private_idx, public_ip_address[private_idx]))
                else:
                    for private_idx in range(len(private_ip_address)):
                        print('party_%s_ip=%s' % (private_idx, private_ip_address[private_idx]))
                        private_ip_file.write('party_%s_ip=%s\n' % (private_idx, private_ip_address[private_idx]))

                port_number = 8000

                for private_idx in range(len(public_ip_address)):
                    print('party_%s_port=%s' % (private_idx, port_number))
                    private_ip_file.write('party_%s_port=%s\n' % (private_idx, port_number))

    # write public ips to file for fabric
    if 'local' in regions or not 'server' in regions:
        with open('public_ips', 'w+') as public_ip_file:
            for public_idx in range(len(public_ip_address)):
                public_ip_file.write('%s\n' % public_ip_address[public_idx])


def check_running_instances():
    with open(config_file_path) as data_file:
        data = json.load(data_file, object_pairs_hook=OrderedDict)
        regions = list(data['regions'].values())

        instances_ids = list()
        instances_count = 0

        for idx in range(len(regions)):
            client = boto3.client('ec2', region_name=regions[idx][:-1])
            response = client.describe_spot_instance_requests()

            for req_idx in range(len(response['SpotInstanceRequests'])):
                if response['SpotInstanceRequests'][req_idx]['State'] == 'active' or \
                                response['SpotInstanceRequests'][req_idx]['State'] == 'open':
                    instances_ids.append(response['SpotInstanceRequests'][req_idx]['InstanceId'])

            ec2 = boto3.resource('ec2', region_name=regions[idx][:-1])
            instances = ec2.instances.filter(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])

            for inst in instances:
                if inst.id in instances_ids:
                    instances_count += 1

        return instances_count


if task_idx == '1':
    deploy_instances()
elif task_idx == '2':
    create_key_pair()
elif task_idx == '3':
    create_security_group()
else:
    raise ValueError('Invalid choice')
