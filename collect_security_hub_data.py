#!/usr/bin/env python3
"""
AWS Security Hub Cost Estimation - Single Account Data Collection

Collects resource usage data for Security Hub pricing estimation.
"""

import boto3
import csv
from datetime import datetime
import argparse


def collect_data(session, region):
    """Collect all required metrics"""
    ec2 = session.client('ec2', region_name=region)
    ecr = session.client('ecr', region_name=region)
    lambda_client = session.client('lambda', region_name=region)
    iam = session.client('iam')
    # Amazon Inspector client
    inspector = session.client('inspector2', region_name=region)
    sts = session.client('sts')
    
    account_id = sts.get_caller_identity()['Account']
    
    # EC2
    instances = ec2.describe_instances()
    ec2_count = sum(len(r['Instances']) for r in instances['Reservations'])
    running = sum(1 for r in instances['Reservations'] 
                  for i in r['Instances'] if i['State']['Name'] == 'running')
    ec2_hours = running * 24 * 30
    
    # ECR
    try:
        repos = ecr.describe_repositories()
        ecr_repos = len(repos['repositories'])
        ecr_images = sum(len(ecr.describe_images(repositoryName=r['repositoryName'])['imageDetails'])
                        for r in repos['repositories'])
    except Exception as e:
        print(f"ECR access error: {e}")
        ecr_repos = ecr_images = 0
    
    # Lambda
    lambda_funcs = []
    paginator = lambda_client.get_paginator('list_functions')
    for page in paginator.paginate():
        lambda_funcs.extend(page['Functions'])
    
    # IAM
    users = []
    user_paginator = iam.get_paginator('list_users')
    for page in user_paginator.paginate():
        users.extend(page['Users'])
    
    roles = []
    role_paginator = iam.get_paginator('list_roles')
    for page in role_paginator.paginate():
        roles.extend(page['Roles'])
    
    # Amazon Inspector
    inspector_enabled = False
    lambda_scanned = 0
    try:
        coverage = inspector.list_coverage(maxResults=100)
        inspector_enabled = True
        lambda_scanned = sum(1 for item in coverage.get('coveredResources', [])
                           if item.get('resourceType') == 'AWS_LAMBDA_FUNCTION')
    except Exception as e:
        print(f"Amazon Inspector not enabled or inaccessible: {e}")
    
    return {
        'account_id': account_id,
        'region': region,
        'ec2_instances': ec2_count,
        'ec2_monthly_hours': ec2_hours,
        'ecr_repositories': ecr_repos,
        'ecr_images': ecr_images,
        'lambda_functions': len(lambda_funcs),
        'iam_users': len(users),
        'iam_roles': len(roles),
        'inspector_enabled': inspector_enabled,
        'lambda_scanned': lambda_scanned
    }


def main():
    parser = argparse.ArgumentParser(description='Collect AWS Security Hub cost estimation data')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--profile', help='AWS profile name')
    args = parser.parse_args()
    
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    
    print(f"Collecting data from region {args.region}...")
    data = collect_data(session, args.region)
    
    # Save CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'security_hub_data_{timestamp}.csv'
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Account ID', 'Region', 'EC2 Instances', 'EC2 Monthly Hours',
            'ECR Repositories', 'ECR Images', 'Lambda Functions',
            'IAM Users', 'IAM Roles', 'Amazon Inspector Enabled', 'Lambda Scanned'
        ])
        writer.writerow([
            data['account_id'], data['region'], data['ec2_instances'],
            data['ec2_monthly_hours'], data['ecr_repositories'], data['ecr_images'],
            data['lambda_functions'], data['iam_users'], data['iam_roles'],
            data['inspector_enabled'], data['lambda_scanned']
        ])
    
    print(f"\n{'='*60}")
    print(f"Account: {data['account_id']} | Region: {data['region']}")
    print(f"{'='*60}")
    print(f"EC2 Instances: {data['ec2_instances']} ({data['ec2_monthly_hours']:,} hours/month)")
    print(f"ECR: {data['ecr_repositories']} repos, {data['ecr_images']} images")
    print(f"Lambda Functions: {data['lambda_functions']}")
    print(f"IAM: {data['iam_users']} users, {data['iam_roles']} roles")
    print(f"Amazon Inspector: {'Enabled' if data['inspector_enabled'] else 'Disabled'} ({data['lambda_scanned']} Lambda scanned)")
    print(f"{'='*60}")
    print(f"\nResults saved to: {filename}")


if __name__ == '__main__':
    main()
