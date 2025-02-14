from xuanpolicy.tensorflow.learners import *


class SACDIS_Learner(Learner):
    def __init__(self,
                 policy: tk.Model,
                 optimizers: Sequence[tk.optimizers.Optimizer],
                 summary_writer: Optional[SummaryWriter] = None,
                 device: str = "cpu:0",
                 modeldir: str = "./",
                 gamma: float = 0.99,
                 tau: float = 0.01):
        self.tau = tau
        self.gamma = gamma
        super(SACDIS_Learner, self).__init__(policy, optimizers, summary_writer, device, modeldir)

    def save_model(self):
        model_path = self.modeldir + "model-%s-%s" % (time.asctime(), str(self.iterations))
        self.policy.actor.save(model_path)

    def load_model(self, path):
        model_names = os.listdir(path)
        try:
            model_names.remove('obs_rms.npy')
            model_names.sort()
            model_path = path + model_names[-1]
            self.policy.actor = tk.models.load_model(model_path, compile=False)
        except:
            raise "Failed to load model! Please train and save the model first."

    def update(self, obs_batch, act_batch, rew_batch, next_batch, terminal_batch):
        self.iterations += 1
        with tf.device(self.device):
            act_batch = tf.convert_to_tensor(act_batch, dtype=tf.int64)
            rew_batch = tf.convert_to_tensor(rew_batch)
            ter_batch = tf.reshape(tf.convert_to_tensor(terminal_batch), [-1, 1])
            act_batch = tf.expand_dims(act_batch, axis=-1)

            # critic update
            with tf.GradientTape() as tape:
                _, action_q = self.policy.Qaction(obs_batch)
                action_q = tf.gather(params=action_q, indices=act_batch, axis=-1, batch_dims=-1)
                # with torch.no_grad():
                _, action_prob_next, log_pi_next, target_q = self.policy.Qtarget(next_batch)
                target_q = action_prob_next * (target_q - 0.01 * log_pi_next)
                target_q = tf.expand_dims(tf.reduce_sum(target_q, axis=1), axis=-1)
                rew = tf.expand_dims(rew_batch, axis=-1)
                backup = rew + (1 - ter_batch) * self.gamma * target_q
                y_true = tf.stop_gradient(tf.reshape(backup, [-1]))
                y_pred = tf.reshape(action_q, [-1])
                q_loss = tk.losses.mean_squared_error(y_true, y_pred)
                gradients = tape.gradient(q_loss, self.policy.critic.trainable_variables)
                self.optimizer[1].apply_gradients([
                    (grad, var)
                    for (grad, var) in zip(gradients, self.policy.critic.trainable_variables)
                    if grad is not None
                ])

            # actor update
            with tf.GradientTape() as tape:
                _, action_prob, log_pi, policy_q = self.policy.Qpolicy(obs_batch)
                inside_term = 0.01 * log_pi - policy_q
                p_loss = tf.reduce_mean(tf.reduce_sum(action_prob * inside_term, axis=-1))
                gradients = tape.gradient(p_loss, self.policy.actor.trainable_variables)
                self.optimizer[0].apply_gradients([
                    (grad, var)
                    for (grad, var) in zip(gradients, self.policy.actor.trainable_variables)
                    if grad is not None
                ])

            self.policy.soft_update(self.tau)

            actor_lr = self.optimizer[0]._decayed_lr(tf.float32)
            critic_lr = self.optimizer[1]._decayed_lr(tf.float32)
            self.writer.add_scalar("Qloss", q_loss.numpy(), self.iterations)
            self.writer.add_scalar("Ploss", p_loss.numpy(), self.iterations)
            self.writer.add_scalar("Qvalue", tf.reduce_mean(action_q).numpy(), self.iterations)
            self.writer.add_scalar("actor_lr", actor_lr.numpy(), self.iterations)
            self.writer.add_scalar("critic_lr", critic_lr.numpy(), self.iterations)
