import json
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('serverless-web-application-on-aws')

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json',
}


def lambda_handler(event, context):
    # Atomic increment — avoids the get/put race the previous version had,
    # and creates the item on first call.
    result = table.update_item(
        Key={'id': '0'},
        UpdateExpression='ADD #v :inc',
        ExpressionAttributeNames={'#v': 'views'},
        ExpressionAttributeValues={':inc': 1},
        ReturnValues='UPDATED_NEW',
    )
    views = int(result['Attributes']['views'])

    return {
        'statusCode': 200,
        'headers': CORS_HEADERS,
        'body': json.dumps(views),
    }
