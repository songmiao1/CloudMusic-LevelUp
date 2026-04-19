const api = require('@neteasecloudmusicapienhanced/api');

function getBody(response) {
  return response && response.body !== undefined ? response.body : response;
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== '';
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function unique(values) {
  return [...new Set(values.filter(hasValue))];
}

function isAlreadyDone(body) {
  const message = `${body?.message || body?.msg || ''}`;
  return body?.code === -2 || message.includes('已签到') || message.includes('重复');
}

function isFatalCode(body) {
  return body?.code === 301 || body?.code === 250 || body?.code === 401;
}

async function call(name, params = {}) {
  const response = await api[name]({
    cookie: process.env.NETEASE_COOKIE,
    ...params,
  });
  const body = getBody(response);

  if (isFatalCode(body)) {
    throw new Error(`${name} failed with code ${body.code}`);
  }

  return body;
}

function logSection(title) {
  console.log(`\n${'='.repeat(50)}`);
  console.log(title);
  console.log('='.repeat(50));
}

function formatTaskState(task) {
  if (task.completed) {
    return '已完成';
  }
  if (task.needReceive || task.needToReceive || task.status === 20) {
    return '可领取';
  }
  return '待完成';
}

function describeYunbeiTasks(tasks, todoLookup) {
  for (const task of tasks) {
    const todo = todoLookup.get(String(task.userTaskId || 0));
    const state = todo?.completed ? '可领奖' : formatTaskState(task);
    console.log(
      `[云贝] ${task.taskName}: ${state} (${task.taskPoint} 云贝)`,
    );
  }
}

function describeVipTasks(groups) {
  for (const group of groups) {
    for (const task of asArray(group.taskItems)) {
      console.log(
        `[黑胶] ${task.action || task.name || '未命名任务'}: ${formatTaskState(task)} (${task.description || '无描述'})`,
      );
    }
  }
}

function describeMusicianTasks(tasks) {
  for (const task of tasks) {
    console.log(
      `[音乐人] ${task.description || task.name || '未命名任务'}: ${formatTaskState(task)} (奖励 ${task.rewardWorth || '?'} / type ${task.rewardType || '?'})`,
    );
  }
}

async function runDailySigns() {
  logSection('扩展任务签到');

  const yunbei = await call('yunbei_sign');
  if (yunbei.code === 200) {
    const amount = yunbei?.data?.yunbeiNum;
    console.log(
      `[云贝签到] ${isAlreadyDone(yunbei) ? '今日已签到' : '执行成功'}${hasValue(amount) ? `，获得 ${amount} 云贝` : ''}`,
    );
  } else {
    console.log(`[云贝签到] 返回 ${JSON.stringify(yunbei)}`);
  }

  const vip = await call('vip_sign');
  if (vip.code === 200 || isAlreadyDone(vip)) {
    console.log(`[黑胶签到] ${isAlreadyDone(vip) ? '今日已签到' : '执行成功'}`);
  } else {
    console.log(`[黑胶签到] 返回 ${JSON.stringify(vip)}`);
  }

  const musician = await call('musician_sign');
  if (musician.code === 200 || isAlreadyDone(musician)) {
    console.log(`[音乐人签到] ${isAlreadyDone(musician) ? '今日已签到' : '执行成功'}`);
  } else {
    console.log(`[音乐人签到] 返回 ${JSON.stringify(musician)}`);
  }
}

async function claimYunbeiRewards() {
  logSection('云贝任务');

  const [tasksBody, todoBody, todayBody] = await Promise.all([
    call('yunbei_tasks'),
    call('yunbei_tasks_todo'),
    call('yunbei_today'),
  ]);

  const tasks = asArray(tasksBody.data);
  const todoList = asArray(todoBody.data);
  const todoLookup = new Map(todoList.map((item) => [String(item.userTaskId || 0), item]));

  describeYunbeiTasks(tasks, todoLookup);
  if (todayBody?.data?.shells !== undefined) {
    console.log(`[云贝余额] 今日累计 ${todayBody.data.shells} 云贝`);
  }

  const claimable = todoList.filter((item) => item.completed && hasValue(item.userTaskId));
  if (!claimable.length) {
    console.log('[云贝领奖] 当前没有可领取任务');
    return;
  }

  for (const item of claimable) {
    const result = await call('yunbei_task_finish', {
      userTaskId: String(item.userTaskId),
      depositCode: String(item.depositCode || 0),
    });
    console.log(
      `[云贝领奖] ${item.taskName}: ${result.code === 200 ? '领取成功' : JSON.stringify(result)}`,
    );
  }
}

async function claimVipRewards() {
  logSection('黑胶任务');

  const body = await call('vip_tasks');
  const groups = asArray(body?.data?.taskList);
  describeVipTasks(groups);

  const ids = unique(
    groups.flatMap((group) =>
      asArray(group.taskItems).flatMap((task) => {
        if (!(task.needReceive || task.status === 20)) {
          return [];
        }
        if (Array.isArray(task.unGetIds)) {
          return task.unGetIds;
        }
        return hasValue(task.unGetIds) ? [task.unGetIds] : [];
      }),
    ),
  );

  if (!ids.length) {
    console.log('[黑胶领奖] 当前没有可领取成长值');
    return;
  }

  const result = await call('vip_growthpoint_get', {
    ids: ids.join(','),
  });
  console.log(
    `[黑胶领奖] ${result.code === 200 ? '领取成功' : JSON.stringify(result)}`,
  );
}

async function claimMusicianRewards() {
  logSection('音乐人任务');

  const body = await call('musician_tasks');
  const tasks = asArray(body?.data?.list);
  describeMusicianTasks(tasks);

  const claimable = tasks.filter(
    (task) => hasValue(task.userMissionId) && (task.status === 20 || task.needToReceive > 0),
  );

  if (!claimable.length) {
    console.log('[音乐人领奖] 当前没有可领取云豆');
    return;
  }

  for (const task of claimable) {
    const result = await call('musician_cloudbean_obtain', {
      id: String(task.userMissionId),
      period: String(task.period || 1),
    });
    console.log(
      `[音乐人领奖] ${task.description || task.name || task.userMissionId}: ${result.code === 200 ? '领取成功' : JSON.stringify(result)}`,
    );
  }
}

async function main() {
  if (!process.env.NETEASE_COOKIE) {
    throw new Error('未找到环境变量 NETEASE_COOKIE');
  }

  console.log('网易云音乐扩展任务执行开始');
  if (process.env.NETEASE_USER_ID) {
    console.log(`用户 ID: ${process.env.NETEASE_USER_ID}`);
  }

  await runDailySigns();
  await claimYunbeiRewards();
  await claimVipRewards();
  await claimMusicianRewards();

  console.log('\n网易云音乐扩展任务执行完成');
}

main().catch((error) => {
  console.error(`任务执行失败: ${error.stack || error.message}`);
  process.exit(1);
});
