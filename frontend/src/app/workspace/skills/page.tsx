"use client";

import {
  PlusIcon,
  SearchIcon,
  SparklesIcon,
  TerminalIcon,
  UploadIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { publishSkill } from "@/core/skills/api";
import { useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";

// ---------------------------------------------------------------------------
// Skill Card
// ---------------------------------------------------------------------------

function SkillCard({ skill }: { skill: Skill }) {
  const router = useRouter();

  const handleLoad = () => {
    router.push(
      `/workspace/chats/new?bind_skill=${encodeURIComponent(skill.name)}&bind_version=latest`,
    );
  };

  return (
    <div className="bg-card flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-start gap-2">
        <div className="bg-primary/10 flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
          <SparklesIcon className="text-primary h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{skill.name}</p>
          {skill.category && (
            <p className="text-muted-foreground truncate text-xs">
              {skill.category}
            </p>
          )}
        </div>
      </div>
      <p className="text-muted-foreground line-clamp-2 flex-1 text-sm">
        {skill.description || "暂无描述"}
      </p>
      <Button
        size="sm"
        variant="outline"
        className="w-full"
        onClick={handleLoad}
      >
        加载到会话
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload Dialog
// ---------------------------------------------------------------------------

const MANIFEST_PLACEHOLDER = `name: my-skill
version: 1.0.0
scope: private
description: A brief description of what this skill does
author: your-name`;

const SKILL_MD_PLACEHOLDER = `---
name: my-skill
description: A brief description of what this skill does
---

# My Skill

Describe what this skill does and how to use it.`;

function UploadSkillDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [manifest, setManifest] = useState("");
  const [skillMd, setSkillMd] = useState("");
  const [isPublishing, setIsPublishing] = useState(false);

  const handlePublish = async () => {
    if (!manifest.trim() || !skillMd.trim()) {
      toast.error("请填写 manifest.yaml 和 SKILL.md 内容");
      return;
    }
    setIsPublishing(true);
    try {
      await publishSkill({ manifest, skill_md: skillMd });
      toast.success("技能发布成功");
      onOpenChange(false);
      setManifest("");
      setSkillMd("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "发布失败，请稍后重试";
      toast.error(message);
    } finally {
      setIsPublishing(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>上传技能</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="editor">
          <TabsList className="w-full">
            <TabsTrigger value="editor" className="flex-1">
              在线编辑
            </TabsTrigger>
            <TabsTrigger value="cli" className="flex-1">
              CLI 提示
            </TabsTrigger>
          </TabsList>

          {/* Online editor tab */}
          <TabsContent value="editor" className="space-y-4 pt-2">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">manifest.yaml</label>
              <Textarea
                className="font-mono text-xs"
                rows={7}
                placeholder={MANIFEST_PLACEHOLDER}
                value={manifest}
                onChange={(e) => setManifest(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">SKILL.md</label>
              <Textarea
                className="font-mono text-xs"
                rows={7}
                placeholder={SKILL_MD_PLACEHOLDER}
                value={skillMd}
                onChange={(e) => setSkillMd(e.target.value)}
              />
            </div>
            <Button
              className="w-full"
              onClick={handlePublish}
              disabled={isPublishing}
            >
              {isPublishing ? "发布中..." : "发布"}
            </Button>
          </TabsContent>

          {/* CLI hint tab */}
          <TabsContent value="cli" className="pt-2">
            <div className="space-y-3">
              <p className="text-muted-foreground text-sm">
                在项目目录内准备好 <code>manifest.yaml</code> 和{" "}
                <code>SKILL.md</code>，然后运行以下命令一键发布：
              </p>
              <div className="bg-muted flex items-center gap-2 rounded-md p-3">
                <TerminalIcon className="text-muted-foreground h-4 w-4 shrink-0" />
                <code className="text-sm">deerflow skill publish</code>
              </div>
              <p className="text-muted-foreground text-xs">
                需要配置 API Token（设置 → 技能 → CLI 令牌）。
              </p>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SkillsPage() {
  const { skills, isLoading } = useSkills();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "mine">("all");
  const [uploadOpen, setUploadOpen] = useState(false);

  const publicSkills = skills.filter((s: Skill) => !s.name.startsWith("user/"));
  const mySkills = skills.filter((s: Skill) => s.name.startsWith("user/"));

  const filterSkills = (list: Skill[]) =>
    list.filter(
      (s) =>
        s.name.toLowerCase().includes(query.toLowerCase()) ||
        s.description?.toLowerCase().includes(query.toLowerCase()),
    );

  const visiblePublic = filterSkills(publicSkills);
  const visibleMine = filterSkills(mySkills);

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">技能广场</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            发现、加载和发布 DeerFlow 技能
          </p>
        </div>
        <Button onClick={() => setUploadOpen(true)}>
          <UploadIcon className="mr-1.5 h-4 w-4" />
          上传技能
        </Button>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 border-b px-6 py-3">
        <div className="relative flex-1">
          <SearchIcon className="text-muted-foreground absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
          <Input
            className="pl-9"
            placeholder="搜索技能..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex gap-1 rounded-md border p-1">
          <Button
            size="sm"
            variant={filter === "all" ? "default" : "ghost"}
            className="h-7 px-3 text-xs"
            onClick={() => setFilter("all")}
          >
            全部
          </Button>
          <Button
            size="sm"
            variant={filter === "mine" ? "default" : "ghost"}
            className="h-7 px-3 text-xs"
            onClick={() => setFilter("mine")}
          >
            我的
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
            加载中...
          </div>
        ) : (
          <>
            {/* All / public skills */}
            {(filter === "all" || filter === "mine") && (
              <section>
                {filter === "all" && (
                  <>
                    {visiblePublic.length === 0 && visibleMine.length === 0 ? (
                      <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
                        <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
                          <SparklesIcon className="text-muted-foreground h-7 w-7" />
                        </div>
                        <div>
                          <p className="font-medium">暂无技能</p>
                          <p className="text-muted-foreground mt-1 text-sm">
                            上传你的第一个技能吧
                          </p>
                        </div>
                        <Button
                          variant="outline"
                          className="mt-2"
                          onClick={() => setUploadOpen(true)}
                        >
                          <PlusIcon className="mr-1.5 h-4 w-4" />
                          上传技能
                        </Button>
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                        {visiblePublic.map((skill) => (
                          <SkillCard key={skill.name} skill={skill} />
                        ))}
                      </div>
                    )}
                  </>
                )}

                {/* My skills section */}
                {(filter === "mine" || visibleMine.length > 0) && (
                  <div className={filter === "all" ? "mt-8" : undefined}>
                    <h2 className="mb-4 text-base font-semibold">我的技能</h2>
                    {visibleMine.length === 0 ? (
                      <p className="text-muted-foreground text-sm">
                        {query
                          ? "未找到匹配的私有技能"
                          : "还没有私有技能，点击「上传技能」发布你的第一个私有技能"}
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                        {visibleMine.map((skill) => (
                          <SkillCard key={skill.name} skill={skill} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </div>

      <UploadSkillDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    </div>
  );
}
