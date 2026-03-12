#!/usr/bin/env python3
"""
AWS Security Hub Cost Estimation - Multi-Account Data Collection

Collects data across multiple AWS accounts using cross-account roles.
"""

import boto3
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse


def assume_role(account_id, role_name):
    """Assume role in target account"""
    sts = boto3.client('sts')
    role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'
    
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName='SecurityHubCostEstimator'
        )
        return boto3.Session(
            aws_access_key_id=response['Credentials']['AccessKeyId'],
            aws_secret_access_key=response['Credentials']['SecretAccessKey'],
            aws_session_token=response['Credentials']['SessionToken']
        )
    except Exception as e:
        print(f"  ERROR: Failed to assume role in {account_id}: {e}")
        return None


def collect_account_data(account_id, role_name, region):
    """Collect data for a single account"""
    print(f"Processing {account_id}...")
    
    session = assume_role(account_id, role_name)
    if not session:
        return {'account_id': account_id, 'region': region, 'error': 'Failed to assume role'}
    
    try:
        ec2 = session.client('ec2', region_name=region)
        ecr = session.client('ecr', region_name=region)
        lambda_client = session.client('lambda', region_name=region)
        iam = session.client('iam')
        # Amazon Inspector client
        inspector = session.client('inspector2', region_name=region)
        
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
            print(f"  ECR access error in {account_id}: {e}")
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
            print(f"  Amazon Inspector not enabled or inaccessible in {account_id}: {e}")
        
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
    except Exception as e:
        return {'account_id': account_id, 'region': region, 'error': str(e)}


def get_org_accounts():
    """Get all active accounts from AWS Organizations"""
    org = boto3.client('organizations')
    accounts = []
    paginator = org.get_paginator('list_accounts')
    for page in paginator.paginate():
        accounts.extend([a for a in page['Accounts'] if a['Status'] == 'ACTIVE'])
    return [a['Id'] for a in accounts]


def main():
    parser = argparse.ArgumentParser(description='Collect Security Hub data across multiple accounts')
    parser.add_argument('--role-name', required=True, help='IAM role name in member accounts')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--accounts', help='Comma-separated account IDs (or use Organizations)')
    parser.add_argument('--max-workers', type=int, default=5, help='Parallel workers (default: 5)')
    args = parser.parse_args()
    
    # Get accounts
    if args.accounts:
        account_ids = [a.strip() for a in args.accounts.split(',')]
        import re
        for acc_id in account_ids:
            if not re.match(r'^\d{12}$', acc_id):
                raise ValueError(f"Invalid account ID format: {acc_id}. Must be 12 digits.")
    else:
        print("Fetching accounts from AWS Organizations...")
        account_ids = get_org_accounts()
    
    print(f"\nCollecting data from {len(account_ids)} accounts...\n")
    
    # Collect in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(collect_account_data, acc, args.role_name, args.region): acc 
                  for acc in account_ids}
        for future in as_completed(futures):
            results.append(future.result())
    
    # Save CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'security_hub_data_multi_{timestamp}.csv'
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Account ID', 'Region', 'EC2 Instances', 'EC2 Monthly Hours',
            'ECR Repositories', 'ECR Images', 'Lambda Functions',
            'IAM Users', 'IAM Roles', 'Amazon Inspector Enabled', 'Lambda Scanned', 'Error'
        ])
        for d in results:
            writer.writerow([
                d.get('account_id', ''), d.get('region', ''),
                d.get('ec2_instances', 0), d.get('ec2_monthly_hours', 0),
                d.get('ecr_repositories', 0), d.get('ecr_images', 0),
                d.get('lambda_functions', 0), d.get('iam_users', 0),
                d.get('iam_roles', 0), d.get('inspector_enabled', False),
                d.get('lambda_scanned', 0), d.get('error', '')
            ])
    
    # Summary
    total_ec2 = sum(d.get('ec2_monthly_hours', 0) for d in results)
    total_lambda = sum(d.get('lambda_functions', 0) for d in results)
    total_ecr = sum(d.get('ecr_images', 0) for d in results)
    
    print(f"\n{'='*60}")
    print(f"Accounts: {len(results)} | Total EC2 Hours: {total_ec2:,}")
    print(f"Total Lambda: {total_lambda:,} | Total ECR Images: {total_ecr:,}")
    print(f"{'='*60}")
    print(f"\nResults saved to: {filename}")


if __name__ == '__main__':
    main()
