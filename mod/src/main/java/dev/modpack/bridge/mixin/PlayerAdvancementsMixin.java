package dev.modpack.bridge.mixin;

import dev.modpack.bridge.ModpackBridge;
import net.minecraft.advancements.Advancement;
import net.minecraft.advancements.AdvancementProgress;
import net.minecraft.advancements.DisplayInfo;
import net.minecraft.server.PlayerAdvancements;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.GameRules;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** В 1.20.1 у Fabric API нет события достижений: ловим момент, когда award() завершает достижение. */
@Mixin(PlayerAdvancements.class)
public abstract class PlayerAdvancementsMixin {
	@Shadow
	private ServerPlayer player;

	@Shadow
	public abstract AdvancementProgress getOrStartProgress(Advancement advancement);

	// award() вызывается только из серверного потока, поэтому хватает поля.
	@Unique
	private boolean modpackBridge$wasDone;

	@Inject(method = "award", at = @At("HEAD"))
	private void modpackBridge$beforeAward(Advancement advancement, String criterion, CallbackInfoReturnable<Boolean> cir) {
		modpackBridge$wasDone = getOrStartProgress(advancement).isDone();
	}

	@Inject(method = "award", at = @At("RETURN"))
	private void modpackBridge$afterAward(Advancement advancement, String criterion, CallbackInfoReturnable<Boolean> cir) {
		if (modpackBridge$wasDone || !getOrStartProgress(advancement).isDone()) {
			return;
		}
		DisplayInfo display = advancement.getDisplay();
		// Как ванилла: только достижения, которые объявляются в чате (без рецептов и скрытых служебных).
		if (display == null || !display.shouldAnnounceChat()) {
			return;
		}
		if (!player.level().getGameRules().getBoolean(GameRules.RULE_ANNOUNCE_ADVANCEMENTS)) {
			return;
		}
		ModpackBridge.onAdvancement(player, display);
	}
}
