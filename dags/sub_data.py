from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.providers.google.cloud.operators.pubsub import PubSubPullOperator
from airflow.decorators import dag
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.operators.python import BranchPythonOperator
from airflow.operators.dummy import DummyOperator
from datetime import datetime, timedelta
import os

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date":datetime(2025, 3, 11, 8, 49),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


dag = DAG(
    "spark_and_gcs",
    default_args=default_args,
    schedule_interval="*/5 * * * *",
    catchup=False,
)
def decide_next_task(**context):
    task_instance = context['task_instance']
    result = context['task_instance'].xcom_pull(key="return_value")
    if result and len(result[0]) > 0:
        return "spark_process"
    return "end_task"

def publish_last_value(**context):
    file_path = "/opt/airflow/logs/publish_last_value.txt"
    if not os.path.exists(file_path):
        publish_last_value = "2000-01-01 00:00:00.000"
        f = open(file_path,'w')
        f.write("2000-01-01 00:00:00.000") #최초 값 세팅
    else:
        f = open(file_path,'r')
        publish_last_value = f.read()
    task_instance = context['task_instance']
    task_instance.xcom_push(key="return_value",value=publish_last_value)

    return publish_last_value

publish_lastvalue = PythonOperator(
    task_id = "publish_lastvalue",
    python_callable = publish_last_value,
    dag=dag
)

get_data = PostgresOperator(
    task_id = "postgres_check",
    postgres_conn_id = "olist_postgres_conn",
    trigger_rule="all_success",
    parameters={"publish_last_value": "{{ ti.xcom_pull(task_ids='publish_lastvalue') }}"},
    sql = """
        SELECT
            *
        FROM
            pubsub.olist_pubsub
        WHERE
            timestamp > TO_TIMESTAMP(%(publish_last_value)s, 'YYYY-MM-DD HH24:MI:SS.MS')
        """
    )


branch_task = BranchPythonOperator(
    task_id="branch_task",
    python_callable=decide_next_task,
    provide_context=True,
    dag=dag
)

end_task = DummyOperator(
    task_id="end_task",
    dag=dag
)

spark_process = SparkKubernetesOperator(
    task_id="spark_process",
    trigger_rule="all_success",
    depends_on_past=True,
    retries=3,
    application_file="olist_spark.yaml",
    namespace="default",
    kubernetes_conn_id="kubernetes-conn-default",
    do_xcom_push=False,
    dag=dag
)

publish_lastvalue >> get_data >> spark_process
